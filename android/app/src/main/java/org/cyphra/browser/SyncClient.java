/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
package org.cyphra.browser;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import org.json.JSONArray;
import org.json.JSONObject;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.Mac;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import javax.net.ssl.HttpsURLConnection;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Manual, opt-in Cyphra desktop-compatible v2 pairing and encrypted sync.
 * Android displays a flat bookmark list. Desktop folders/separators, Shield
 * exceptions and unsupported selected preferences are retained as opaque
 * encrypted records, never erased simply because Android cannot display them.
 * Only HTTP(S) bookmarks and the history-saving setting are applied here.
 */
public final class SyncClient {
    static final int MAX_BYTES = 2 * 1024 * 1024;
    private static final int MAX_RESPONSE = MAX_BYTES * 4 / 3 + 4096;
    private static final int MAX_STATE = 6 * 1024 * 1024;
    private static final long MAX_INTEGER = 9007199254740991L;
    private static final String CONFIG = "sync-config-encrypted-v2";
    private static final String STATE = "sync-state-v2";
    private static final String LABEL = "sync-server-label-v2";
    private static final String HISTORY = "p:places.history.enabled";
    private static final Set<String> ROOTS = choices("menu________", "toolbar_____", "unfiled_____", "mobile______");
    private static final Pattern ID = Pattern.compile("[a-f0-9]{32}");
    private static final Pattern GUID = Pattern.compile("[A-Za-z0-9_-]{12}");
    private static final Pattern TOKEN = Pattern.compile("[A-Za-z0-9_-]{43}");
    private static final Pattern PAIR = Pattern.compile("cyphra-sync-v2\\.([A-Za-z0-9_-]+)\\.([a-f0-9]{32})\\.([A-Za-z0-9_-]{43})\\.(team|public|home)\\.(work|personal)");
    private static final ConcurrentHashMap<String, Object> LOCKS = new ConcurrentHashMap<>();
    private static final SecureRandom RANDOM = new SecureRandom();
    private final Context context;
    private final BrowserStore store;
    private final SharedPreferences data;
    private final Object lock;

    public static final class Result {
        public final long revision;
        public final int bookmarks, items;
        Result(long revision, int bookmarks, int items) {
            this.revision = revision; this.bookmarks = bookmarks; this.items = items;
        }
        @Override public String toString() {
            return "Synced " + bookmarks + " bookmark" + (bookmarks == 1 ? "" : "s") + " · revision " + revision;
        }
    }

    public SyncClient(Context context, BrowserStore store) {
        this.context = context.getApplicationContext(); this.store = store;
        // BrowserStore owns this same, mode-specific local preference file.
        // One commit keeps imported bookmarks and their sync baseline together.
        data = this.context.getSharedPreferences("cyphra-data-" + store.mode(), Context.MODE_PRIVATE);
        lock = LOCKS.computeIfAbsent(this.context.getPackageName() + ":" + store.edition() + ":" + store.mode(), ignored -> new Object());
    }

    public boolean isPaired() { return !data.getString(CONFIG, "").isEmpty(); }
    /** Display metadata only; requests use the authenticated encrypted config. */
    public String endpoint() { return isPaired() ? data.getString(LABEL, "") : ""; }

    public String create(String endpoint, String invitation) throws Exception {
        background();
        synchronized (lock) {
            unpaired();
            String base = endpointURL(endpoint);
            String invite = invitation == null ? "" : invitation.trim();
            if (!TOKEN.matcher(invite).matches()) throw failure("Enter the server invitation token.");
            String vault = randomID(), secret = b64(random(32));
            Keys keys = keys(secret);
            JSONObject state = capture(newState(), snapshot());
            JSONObject body = new JSONObject().put("vault", vault).put("token", keys.token)
                .put("envelope", encryptPayload(state, secret, vault));
            JSONObject reply = request(base, "/v1/vaults", invite, "POST", body);
            if (revision(reply) != 1) throw failure("The sync server returned an invalid creation revision.");
            JSONObject config = configuration(base, vault, secret, 1);
            commitConfiguration(config, state);
            return pairingCode(config);
        }
    }

    public void pair(String endpoint, String pairingCode) throws Exception {
        background();
        synchronized (lock) {
            unpaired();
            JSONObject parsed = parsePairingCode(pairingCode);
            assertScope(parsed.getJSONObject("scope"), scope());
            String base = parsed.getString("endpoint");
            if (endpoint != null && !endpoint.trim().isEmpty() && !endpointURL(endpoint).equals(base))
                throw failure("The pairing code belongs to a different sync server. Use the server included in that code.");
            String vault = parsed.getString("vault"), secret = parsed.getString("secret");
            JSONObject remote = request(base, "/v1/vaults/" + vault, keys(secret).token, "GET", null);
            long serverRevision = revision(remote);
            if (serverRevision < 1) throw failure("The sync server returned an invalid revision.");
            JSONObject payload = decryptPayload(remote.getJSONObject("envelope"), secret, vault);
            assertPayloadScope(payload, scope());
            // Pairing authenticates the vault. Importing remains a separate,
            // explicit Sync now operation and merges existing local bookmarks.
            commitConfiguration(configuration(base, vault, secret, 0), newState());
        }
    }

    public String pairingCode() throws Exception {
        background();
        synchronized (lock) { return pairingCode(readConfiguration()); }
    }

    public Result sync() throws Exception {
        background();
        synchronized (lock) {
            JSONObject config = readConfiguration();
            String base = config.getString("endpoint"), vault = config.getString("vault"), secret = config.getString("secret");
            String token = keys(secret).token;
            JSONObject state = readState();
            for (int attempt = 0; attempt < 4; attempt++) {
                state = capture(state, snapshot());
                JSONObject remote = request(base, "/v1/vaults/" + vault, token, "GET", null);
                long serverRevision = revision(remote);
                if (serverRevision < 1 || serverRevision < integer(config.get("revision")))
                    throw failure("The sync server returned an older or invalid revision.");
                JSONObject remotePayload = decryptPayload(remote.getJSONObject("envelope"), secret, vault);
                assertPayloadScope(remotePayload, scope());
                state.put("clock", Math.max(integer(state.get("clock")), maxClock(remotePayload)));
                JSONObject baseline = snapshot();
                state = capture(state, baseline);
                JSONObject merged = mergePayloads(state, remotePayload);
                JSONObject body = new JSONObject().put("revision", serverRevision)
                    .put("envelope", encryptPayload(merged, secret, vault));
                JSONObject reply = request(base, "/v1/vaults/" + vault, token, "PUT", body);
                if (reply.optBoolean("conflict", false)) { commitState(state); continue; }
                long updatedRevision = revision(reply);
                if (serverRevision == MAX_INTEGER || updatedRevision != serverRevision + 1)
                    throw failure("The sync server returned an invalid update revision.");
                config.put("revision", updatedRevision);
                return applyAndCommit(state, merged, baseline, config);
            }
            throw failure("Another device is changing this vault. Try syncing again.");
        }
    }

    /** Disconnect never contacts or deletes the server vault or local bookmarks. */
    public void disconnect() {
        synchronized (lock) {
            if (!data.edit().remove(CONFIG).remove(STATE).remove(LABEL).commit())
                throw new IllegalStateException("The sync configuration could not be removed. Try again.");
            try {
                KeyStore keys = KeyStore.getInstance("AndroidKeyStore"); keys.load(null);
                if (keys.containsAlias(alias())) keys.deleteEntry(alias());
            } catch (Exception ignored) {
                // No ciphertext or vault credential remains. A retained,
                // non-exportable wrapping key cannot authorize server access.
            }
        }
    }

    private JSONObject scope() throws Exception {
        return new JSONObject().put("edition", store.edition()).put("mode", store.mode());
    }
    private void unpaired() {
        if (isPaired()) throw new IllegalStateException("Disconnect this device before pairing another vault.");
    }
    private static void background() {
        if (Looper.myLooper() == Looper.getMainLooper())
            throw new IllegalStateException("Run sync from a background task.");
    }

    static String endpointURL(String input) throws Exception {
        try {
            if (input == null || input.length() > 2048 || !input.equals(input.trim())) throw new Exception();
            URI url = new URI(input);
            String path = url.getRawPath();
            if (path == null || path.isEmpty()) path = "/";
            if (!path.endsWith("/")) path += "/";
            if (!"https".equalsIgnoreCase(url.getScheme()) || url.getHost() == null
                || url.getRawUserInfo() != null || url.getRawQuery() != null || url.getRawFragment() != null
                || (url.getPort() != -1 && (url.getPort() < 1 || url.getPort() > 65535))
                || !path.matches("/(?:[A-Za-z0-9_-]+/)*")) throw new Exception();
            // Match the desktop URL constructor's lowercase host and removal
            // of HTTPS's default port, then omit the terminal slash.
            String host = url.getHost().toLowerCase(java.util.Locale.ROOT);
            if (host.contains(":") && !host.startsWith("[")) host = "[" + host + "]";
            int port = url.getPort();
            return "https://" + host + (port == -1 || port == 443 ? "" : ":" + port)
                + path.substring(0, path.length() - 1);
        } catch (Exception error) {
            throw failure("Sync requires an HTTPS server without credentials, query or fragment.");
        }
    }

    static JSONObject parsePairingCode(String input) throws Exception {
        if (input == null || input.trim().length() > 4096) throw failure("Enter a complete Cyphra v2 pairing code.");
        Matcher match = PAIR.matcher(input.trim());
        if (!match.matches()) throw failure("Enter a complete Cyphra v2 pairing code with its edition and mode.");
        String secret = match.group(3);
        if (unb64(secret, 32).length != 32) throw failure("The pairing code has an invalid secret.");
        JSONObject scope=validateScope(new JSONObject().put("edition",match.group(4)).put("mode",match.group(5)));
        return new JSONObject().put("endpoint", endpointURL(utf8(unb64(match.group(1), 2048))))
            .put("vault", match.group(2)).put("secret", secret)
            .put("scope", scope);
    }
    private static String pairingCode(JSONObject config) throws Exception {
        JSONObject scope = config.getJSONObject("scope");
        return "cyphra-sync-v2." + b64(config.getString("endpoint").getBytes(StandardCharsets.UTF_8)) + "."
            + config.getString("vault") + "." + config.getString("secret") + "."
            + scope.getString("edition") + "." + scope.getString("mode");
    }

    static final class Keys {
        final SecretKey encryption;
        final String token;
        Keys(SecretKey encryption, String token) { this.encryption = encryption; this.token = token; }
    }
    /** RFC 5869 HKDF, identical salt/info labels to desktop's WebCrypto. */
    static Keys keys(String secret) throws Exception {
        byte[] raw = unb64(secret, 32), prk = null, encryption = null, authentication = null;
        if (raw.length != 32) throw failure("The pairing code has an invalid secret.");
        try {
            prk = hmac("Cyphra Sync v1".getBytes(StandardCharsets.UTF_8), raw);
            encryption = expand(prk, "encryption");
            authentication = expand(prk, "authentication");
            return new Keys(new SecretKeySpec(encryption, "AES"), b64(hmac(authentication,
                "Cyphra vault access v1".getBytes(StandardCharsets.UTF_8))));
        } finally {
            Arrays.fill(raw, (byte) 0);
            if (prk != null) Arrays.fill(prk, (byte) 0);
            if (encryption != null) Arrays.fill(encryption, (byte) 0);
            if (authentication != null) Arrays.fill(authentication, (byte) 0);
        }
    }
    private static byte[] expand(byte[] prk, String label) throws Exception {
        byte[] info = label.getBytes(StandardCharsets.UTF_8);
        byte[] input = Arrays.copyOf(info, info.length + 1); input[input.length - 1] = 1;
        return hmac(prk, input); // Exactly one SHA-256 block for 256-bit keys.
    }
    private static byte[] hmac(byte[] key, byte[] input) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256"); mac.init(new SecretKeySpec(key, "HmacSHA256")); return mac.doFinal(input);
    }

    static JSONObject encryptPayload(JSONObject payload, String secret, String vault) throws Exception {
        requireID(vault);
        byte[] plaintext = validatePayload(payload).toString().getBytes(StandardCharsets.UTF_8);
        if (plaintext.length > MAX_BYTES - 256) throw failure("Sync data exceeds the 2 MiB limit.");
        try {
            byte[] nonce = random(12);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, keys(secret).encryption, new GCMParameterSpec(128, nonce));
            cipher.updateAAD(("Cyphra Sync v1:" + vault).getBytes(StandardCharsets.UTF_8));
            return new JSONObject().put("version", 1).put("nonce", b64(nonce)).put("ciphertext", b64(cipher.doFinal(plaintext)));
        } finally { Arrays.fill(plaintext, (byte) 0); }
    }
    static JSONObject decryptPayload(JSONObject envelope, String secret, String vault) throws Exception {
        requireID(vault);
        if (integer(envelope.get("version")) != 1 || envelope.length() != 3)
            throw failure("Invalid encrypted sync envelope.");
        byte[] nonce = unb64(envelope.getString("nonce"), 12);
        byte[] ciphertext = unb64(envelope.getString("ciphertext"), MAX_BYTES);
        if (nonce.length != 12 || ciphertext.length < 16) throw failure("Invalid encrypted sync envelope.");
        byte[] plaintext;
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, keys(secret).encryption, new GCMParameterSpec(128, nonce));
            cipher.updateAAD(("Cyphra Sync v1:" + vault).getBytes(StandardCharsets.UTF_8));
            plaintext = cipher.doFinal(ciphertext);
        } catch (Exception error) { throw failure("Sync data could not be authenticated. Check the pairing code."); }
        try {
            if (plaintext.length > MAX_BYTES) throw failure("Sync data is too large.");
            return validatePayload(new JSONObject(utf8(plaintext)));
        } finally { Arrays.fill(plaintext, (byte) 0); }
    }

    static JSONObject validatePayload(JSONObject input) throws Exception {
        if (integer(input.get("version")) != 1) throw failure("Invalid sync data.");
        JSONObject records = input.getJSONObject("records");
        if (records.length() > 15000) throw failure("Too many synchronized items.");
        JSONObject clean = new JSONObject();
        for (String key : names(records)) {
            JSONObject record = records.getJSONObject(key);
            if (integer(record.get("clock")) < 1 || !(record.get("deleted") instanceof Boolean))
                throw failure("Invalid sync change record.");
            requireID(record.getString("device"));
            boolean deleted = record.getBoolean("deleted");
            if (key.startsWith("b:")) {
                String guid = key.substring(2);
                if (!GUID.matcher(guid).matches() || ROOTS.contains(guid) || forbiddenRoot(guid))
                    throw failure("Invalid bookmark identifier.");
                if (!deleted) {
                    JSONObject value = record.getJSONObject("value");
                    String parent = value.getString("parentGuid");
                    long type = integer(value.get("type")), index = integer(value.get("index"));
                    if (!guid.equals(value.getString("guid")) || !GUID.matcher(parent).matches() || forbiddenRoot(parent)
                        || type < 1 || type > 3 || !(value.get("title") instanceof String)
                        || value.getString("title").length() > 4096 || index > 15000)
                        throw failure("Invalid synchronized bookmark.");
                    if (type == 1 && !BrowserStore.isWebURL(value.getString("url")))
                        throw failure("Only HTTP(S) bookmarks can be synchronized.");
                }
            } else if (key.startsWith("p:")) {
                if (deleted || !safePreference(key.substring(2), record.get("value")))
                    throw failure("Unsafe preference in sync data.");
            } else if (key.startsWith("s:")) {
                if (!webOrigin(key.substring(2)) || (!deleted && !choices("off", "strict", "standard").contains(record.getString("value"))))
                    throw failure("Invalid synchronized Shield exception.");
            } else throw failure("Unsupported synchronized item.");
            clean.put(key, copy(record));
        }
        for (String key : names(clean)) {
            JSONObject record = clean.getJSONObject(key);
            if (!key.startsWith("b:") || record.getBoolean("deleted")) continue;
            JSONObject value = record.getJSONObject("value");
            HashSet<String> visited = new HashSet<>(); visited.add(value.getString("guid"));
            String parent = value.getString("parentGuid");
            while (clean.has("b:" + parent) && !clean.getJSONObject("b:" + parent).getBoolean("deleted")) {
                if (!visited.add(parent)) throw failure("Synchronized bookmark folders contain a cycle.");
                JSONObject ancestor = clean.getJSONObject("b:" + parent).getJSONObject("value");
                if (integer(ancestor.get("type")) != 2) throw failure("Synchronized bookmark parent is not a folder.");
                parent = ancestor.getString("parentGuid");
            }
        }
        JSONObject result = new JSONObject().put("version", 1).put("records", clean);
        if (input.has("scope")) result.put("scope", validateScope(input.getJSONObject("scope")));
        return result;
    }
    private static boolean forbiddenRoot(String guid) { return "root________".equals(guid) || "tags________".equals(guid); }
    private static boolean safePreference(String name, Object value) {
        switch (name) {
            case "browser.uidensity": return value instanceof Number && ((Number)value).doubleValue() == ((Number)value).intValue()
                && ((Number)value).intValue() >= 0 && ((Number)value).intValue() <= 2;
            case "browser.toolbars.bookmarks.visibility": return value instanceof String && choices("always", "never", "newtab").contains(value);
            case "browser.download.useDownloadDir": case "signon.rememberSignons": case "places.history.enabled":
            case "privacy.resistFingerprinting": case "webgl.disabled": return value instanceof Boolean;
            default: return false;
        }
    }
    private static boolean webOrigin(String input) {
        try {
            URI uri = new URI(input);
            if (!BrowserStore.isWebURL(input) || uri.getRawQuery() != null || uri.getRawFragment() != null
                || (uri.getRawPath() != null && !uri.getRawPath().isEmpty())) return false;
            String scheme = uri.getScheme().toLowerCase(java.util.Locale.ROOT);
            String host = uri.getHost().toLowerCase(java.util.Locale.ROOT);
            int port = uri.getPort();
            if (port == ("https".equals(scheme) ? 443 : 80)) port = -1;
            return new URI(scheme, null, host, port, null, null, null).toString().equals(input);
        } catch (Exception error) { return false; }
    }
    static JSONObject validateScope(JSONObject value) throws Exception {
        if (value.length() != 2 || !EditionPolicy.allowsMode(value.getString("edition"),value.getString("mode")))
            throw failure("Invalid edition or profile sync binding.");
        return new JSONObject().put("edition", value.getString("edition")).put("mode", value.getString("mode"));
    }
    static void assertScope(JSONObject actual, JSONObject expected) throws Exception {
        if (!same(validateScope(actual), validateScope(expected)))
            throw failure("This sync vault belongs to a different Cyphra edition or mode.");
    }
    static void assertPayloadScope(JSONObject payload, JSONObject expected) throws Exception {
        if (!payload.has("scope")) throw failure("This sync vault lost its Work/Personal binding. No data was imported.");
        assertScope(payload.getJSONObject("scope"), expected);
    }

    static JSONObject mergePayloads(JSONObject left, JSONObject right) throws Exception {
        JSONObject a = validatePayload(left), b = validatePayload(right);
        if (a.has("scope") != b.has("scope")) throw failure("Sync vaults cannot be merged across bindings.");
        if (a.has("scope")) assertScope(a.getJSONObject("scope"), b.getJSONObject("scope"));
        JSONObject records = copy(a.getJSONObject("records"));
        JSONObject incoming = b.getJSONObject("records");
        for (String key : names(incoming)) {
            JSONObject remote = incoming.getJSONObject(key), local = records.optJSONObject(key);
            long rc = integer(remote.get("clock")), lc = local == null ? -1 : integer(local.get("clock"));
            int deviceOrder = local == null ? 1 : remote.getString("device").compareTo(local.getString("device"));
            if (local == null || rc > lc || (rc == lc && deviceOrder > 0)) records.put(key, copy(remote));
            else if (rc == lc && deviceOrder == 0 && !same(remote, local))
                throw failure("Conflicting sync records have the same identity.");
        }
        records.remove("p:privacy.resistFingerprinting"); records.remove("p:webgl.disabled");
        JSONObject result = new JSONObject().put("version", 1).put("records", records);
        if (a.has("scope")) result.put("scope", a.getJSONObject("scope"));
        return validatePayload(result);
    }

    private JSONObject newState() throws Exception {
        return new JSONObject().put("version", 1).put("scope", scope()).put("device", randomID())
            .put("clock", 0).put("records", new JSONObject()).put("baseline", new JSONObject());
    }
    private JSONObject readState() throws Exception {
        String serialized = data.getString(STATE, "");
        if (serialized.isEmpty()) throw failure("The local sync state is missing. Disconnect and pair again.");
        if (serialized.length() > MAX_STATE) throw failure("The local sync state is too large. Disconnect and pair again.");
        JSONObject value = new JSONObject(serialized);
        assertPayloadScope(validatePayload(value), scope()); requireID(value.getString("device"));
        integer(value.get("clock"));
        JSONObject baseline = value.getJSONObject("baseline");
        if (baseline.length() > 4000) throw failure("Invalid local bookmark baseline.");
        for (String url : names(baseline)) {
            if (!BrowserStore.isWebURL(url) || !(baseline.get(url) instanceof String)
                || baseline.getString(url).length() > 512) throw failure("Invalid local bookmark baseline.");
        }
        return value;
    }
    private JSONObject snapshot() throws Exception {
        synchronized (store) {
            JSONObject result = new JSONObject(), bookmarks = new JSONObject();
            JSONArray local = store.bookmarks();
            for (int i = 0; i < local.length(); i++) {
                JSONObject item = local.optJSONObject(i);
                if (item != null && BrowserStore.isWebURL(item.optString("url"))) bookmarks.put(item.getString("url"), item.optString("title"));
            }
            return result.put("bookmarks", bookmarks).put("history", store.booleanPref("save-history", "personal".equals(store.mode())));
        }
    }
    private JSONObject capture(JSONObject input, JSONObject snapshot) throws Exception {
        JSONObject state = copy(input), records = state.getJSONObject("records"), baseline = state.getJSONObject("baseline");
        JSONObject local = snapshot.getJSONObject("bookmarks");
        records.remove("p:privacy.resistFingerprinting"); records.remove("p:webgl.disabled");
        long clock = Math.max(integer(state.get("clock")), maxClock(state));
        Map<String, List<String>> mapping = bookmarkMapping(records);
        int index = 0;
        for (String url : names(local)) {
            String title = local.getString(url);
            if (baseline.has(url) && title.equals(baseline.getString(url))) { index++; continue; }
            List<String> keys = mapping.get(url);
            if (keys == null || keys.isEmpty()) {
                String guid; do { guid = b64(random(9)); } while (records.has("b:" + guid) || ROOTS.contains(guid));
                JSONObject value = new JSONObject().put("guid", guid).put("parentGuid", "mobile______")
                    .put("type", 1).put("index", index).put("title", title).put("url", url);
                records.put("b:" + guid, change(++clock, state.getString("device"), false, value));
            } else for (String key : keys) {
                JSONObject value = copy(records.getJSONObject(key).getJSONObject("value"));
                value.put("title", title);
                records.put(key, change(++clock, state.getString("device"), false, value));
            }
            index++;
        }
        for (String url : names(baseline)) {
            if (local.has(url)) continue;
            for (String key : mapping.getOrDefault(url, Collections.emptyList()))
                records.put(key, change(++clock, state.getString("device"), true, null));
        }
        JSONObject oldHistory = records.optJSONObject(HISTORY);
        boolean history = snapshot.getBoolean("history");
        if (oldHistory == null || !Boolean.valueOf(history).equals(oldHistory.opt("value")))
            records.put(HISTORY, change(++clock, state.getString("device"), false, history));
        if (clock > MAX_INTEGER) throw failure("The sync change clock is exhausted. Create a new vault.");
        state.put("clock", clock).put("baseline", copy(local));
        validatePayload(state);
        return state;
    }
    private static JSONObject change(long clock, String device, boolean deleted, Object value) throws Exception {
        JSONObject record = new JSONObject().put("clock", clock).put("device", device).put("deleted", deleted);
        if (!deleted) record.put("value", value);
        return record;
    }
    private static Map<String, List<String>> bookmarkMapping(JSONObject records) throws Exception {
        Map<String, List<String>> result = new LinkedHashMap<>();
        for (String key : names(records)) {
            JSONObject record = records.getJSONObject(key);
            if (!key.startsWith("b:") || record.getBoolean("deleted")) continue;
            JSONObject value = record.getJSONObject("value");
            if (integer(value.get("type")) != 1) continue;
            result.computeIfAbsent(value.getString("url"), ignored -> new ArrayList<>()).add(key);
        }
        return result;
    }

    private Result applyAndCommit(JSONObject state, JSONObject merged, JSONObject baseline, JSONObject config) throws Exception {
        synchronized (store) {
            JSONObject current = snapshot(), before = baseline.getJSONObject("bookmarks"), now = current.getJSONObject("bookmarks");
            JSONObject records = merged.getJSONObject("records");
            Map<String, JSONObject> rows = new LinkedHashMap<>();
            JSONArray existing = store.bookmarks();
            for (int i = 0; i < existing.length(); i++) {
                JSONObject item = existing.getJSONObject(i); rows.put(item.getString("url"), copy(item));
            }
            Set<String> edited = new HashSet<>();
            Set<String> all = new HashSet<>(names(before)); all.addAll(names(now));
            for (String url : all) if (!same(before.opt(url), now.opt(url))) edited.add(url);
            Map<String, List<String>> live = bookmarkMapping(records);
            // A remote tombstone removes a displayed URL only when no other
            // surviving bookmark GUID still represents that same URL.
            for (String url : names(before)) if (!edited.contains(url) && !live.containsKey(url)) rows.remove(url);
            for (Map.Entry<String, List<String>> entry : live.entrySet()) {
                String url = entry.getKey();
                if (edited.contains(url) || (!rows.containsKey(url) && rows.size() >= 2000)) continue;
                // Prefer deterministic GUID order when a desktop has duplicate
                // URLs; all GUIDs and folder metadata remain in the vault.
                Collections.sort(entry.getValue());
                JSONObject value = records.getJSONObject(entry.getValue().get(0)).getJSONObject("value");
                String title = value.getString("title"); title = title.substring(0, Math.min(512, title.length()));
                JSONObject item = rows.get(url);
                if (item == null) item = new JSONObject().put("url", url).put("visited", System.currentTimeMillis());
                item.put("title", title); rows.put(url, item);
            }
            JSONArray bookmarks = new JSONArray(); JSONObject nextBaseline = new JSONObject();
            for (Map.Entry<String, JSONObject> entry : rows.entrySet()) {
                bookmarks.put(entry.getValue()); nextBaseline.put(entry.getKey(), entry.getValue().optString("title"));
            }
            // Do not swallow edits made while the PUT was in flight. Keeping
            // their earlier baseline makes the next sync publish those edits.
            for (String url : edited) {
                if (before.has(url)) nextBaseline.put(url, before.getString(url)); else nextBaseline.remove(url);
            }
            state.put("records", copy(records)).put("scope", scope()).put("baseline", nextBaseline)
                .put("clock", Math.max(integer(state.get("clock")), maxClock(merged)));
            String serializedState = state.toString();
            if (serializedState.length() > MAX_STATE) throw failure("Local sync state exceeds its storage limit.");
            SharedPreferences.Editor edit = data.edit().putString("bookmarks", bookmarks.toString())
                .putString(STATE, serializedState).putString(CONFIG, encryptConfiguration(config)).putString(LABEL, config.getString("endpoint"));
            JSONObject history = records.optJSONObject(HISTORY);
            if (history != null && same(current.get("history"), baseline.get("history")))
                edit.putBoolean("save-history", history.getBoolean("value"));
            if (!edit.commit()) throw failure("Synced data could not be saved locally. Try syncing again.");
            int items = 0; for (String key : names(records)) if (!records.getJSONObject(key).getBoolean("deleted")) items++;
            return new Result(integer(config.get("revision")), bookmarks.length(), items);
        }
    }

    private JSONObject configuration(String endpoint, String vault, String secret, long revision) throws Exception {
        return new JSONObject().put("version", 2).put("endpoint", endpoint).put("vault", vault).put("secret", secret)
            .put("scope", scope()).put("revision", revision);
    }
    private JSONObject readConfiguration() throws Exception {
        String saved = data.getString(CONFIG, "");
        if (saved.isEmpty()) throw failure("Pair this device before synchronizing.");
        try {
            if (saved.length() > 8192) throw new Exception();
            JSONObject encrypted = new JSONObject(saved);
            byte[] iv = unb64(encrypted.getString("iv"), 12), ciphertext = unb64(encrypted.getString("data"), 4096);
            if (iv.length != 12 || ciphertext.length < 16) throw new Exception();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, credentialKey(false), new GCMParameterSpec(128, iv)); cipher.updateAAD(binding());
            byte[] plaintext = cipher.doFinal(ciphertext);
            try {
                JSONObject result = new JSONObject(utf8(plaintext));
                if (integer(result.get("version")) != 2 || !endpointURL(result.getString("endpoint")).equals(result.getString("endpoint"))) throw new Exception();
                assertScope(result.getJSONObject("scope"), scope()); requireID(result.getString("vault"));
                if (unb64(result.getString("secret"), 32).length != 32) throw new Exception();
                integer(result.get("revision")); return result;
            } finally { Arrays.fill(plaintext, (byte) 0); }
        } catch (Exception error) {
            throw failure("The saved sync configuration cannot be unlocked. Disconnect and pair again.");
        }
    }
    private void commitConfiguration(JSONObject config, JSONObject state) throws Exception {
        if (state.toString().length() > MAX_STATE) throw failure("The local sync state is too large.");
        if (!data.edit().putString(CONFIG, encryptConfiguration(config)).putString(STATE, state.toString())
            .putString(LABEL, config.getString("endpoint")).commit()) throw failure("The sync configuration could not be saved.");
    }
    private void commitState(JSONObject state) throws Exception {
        String value = state.toString();
        if (value.length() > MAX_STATE || !data.edit().putString(STATE, value).commit()) throw failure("The local sync state could not be saved.");
    }
    private String encryptConfiguration(JSONObject config) throws Exception {
        byte[] plaintext = config.toString().getBytes(StandardCharsets.UTF_8);
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, credentialKey(true)); cipher.updateAAD(binding());
            return new JSONObject().put("iv", b64(cipher.getIV())).put("data", b64(cipher.doFinal(plaintext))).toString();
        } finally { Arrays.fill(plaintext, (byte) 0); }
    }
    private String alias() { return context.getPackageName() + ".sync.v2." + store.edition() + "." + store.mode(); }
    private byte[] binding() {
        return (context.getPackageName() + "\nCyphra Sync v2\n" + store.edition() + "\n" + store.mode()).getBytes(StandardCharsets.UTF_8);
    }
    private SecretKey credentialKey(boolean create) throws Exception {
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore"); keys.load(null);
        if (!keys.containsAlias(alias())) {
            if (!create) throw failure("The device sync key is missing.");
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias(), KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).setRandomizedEncryptionRequired(true).build()); generator.generateKey();
        }
        return (SecretKey) keys.getKey(alias(), null);
    }

    private static JSONObject request(String endpoint, String path, String token, String method, JSONObject body) throws Exception {
        if (!endpointURL(endpoint).equals(endpoint) || !TOKEN.matcher(token).matches()
            || !(path.equals("/v1/vaults") && "POST".equals(method)
                || path.matches("/v1/vaults/[a-f0-9]{32}") && choices("GET", "PUT").contains(method)))
            throw failure("Invalid sync request scope.");
        HttpsURLConnection connection = (HttpsURLConnection)new URI(endpoint + path).toURL().openConnection();
        try {
            connection.setSSLSocketFactory(UpdateClient.secureSocketFactory());
            // Use Android's normal certificate and hostname verification. Never
            // follow a redirect with the invitation or derived vault token.
            connection.setInstanceFollowRedirects(false); connection.setUseCaches(false);
            connection.setConnectTimeout(20000); connection.setReadTimeout(20000); connection.setRequestMethod(method);
            connection.setRequestProperty("Authorization", "Bearer " + token);
            connection.setRequestProperty("Accept", "application/json"); connection.setRequestProperty("Cookie", "");
            connection.setRequestProperty("Cache-Control", "no-store");
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > MAX_RESPONSE) throw failure("Sync request is too large.");
                connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json");
                connection.setFixedLengthStreamingMode(bytes.length);
                try (java.io.OutputStream out = connection.getOutputStream()) { out.write(bytes); }
            }
            int status = connection.getResponseCode();
            if (status == 409 && "PUT".equals(method)) return new JSONObject().put("conflict", true);
            if (status < 200 || status > 299) throw failure(status == 401 ? "Sync authorization failed. Check the invitation or pairing code."
                : status >= 300 && status <= 399 ? "Sync server redirects are refused. Use its final HTTPS address."
                : "Sync server returned HTTP " + status + ".");
            long size = connection.getContentLengthLong();
            if (size > MAX_RESPONSE) throw failure("Sync response is too large.");
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream in = connection.getInputStream()) {
                byte[] buffer = new byte[32768]; int count;
                while ((count = in.read(buffer)) != -1) {
                    if (bytes.size() + count > MAX_RESPONSE) throw failure("Sync response is too large.");
                    bytes.write(buffer, 0, count);
                }
            }
            return new JSONObject(utf8(bytes.toByteArray()));
        } finally { connection.disconnect(); }
    }

    private static long revision(JSONObject reply) throws Exception { return integer(reply.get("revision")); }
    private static long integer(Object value) throws Exception {
        if (!(value instanceof Number)) throw failure("Invalid sync integer.");
        double n = ((Number)value).doubleValue(); long result = ((Number)value).longValue();
        if (!Double.isFinite(n) || n != result || result < 0 || result > MAX_INTEGER) throw failure("Invalid sync integer.");
        return result;
    }
    private static long maxClock(JSONObject payload) throws Exception {
        long result = 0; JSONObject records = payload.getJSONObject("records");
        for (String key : names(records)) result = Math.max(result, integer(records.getJSONObject(key).get("clock")));
        return result;
    }
    private static void requireID(String id) throws Exception { if (!ID.matcher(id).matches()) throw failure("Invalid sync identifier."); }
    private static byte[] random(int size) { byte[] value = new byte[size]; RANDOM.nextBytes(value); return value; }
    private static String randomID() {
        StringBuilder value = new StringBuilder(); for (byte b : random(16)) value.append(String.format(java.util.Locale.ROOT, "%02x", b & 255)); return value.toString();
    }
    private static String b64(byte[] value) { return Base64.getUrlEncoder().withoutPadding().encodeToString(value); }
    private static byte[] unb64(String value, int max) throws Exception {
        if (value == null || value.length() > (long)max * 4 / 3 + 4 || !value.matches("[A-Za-z0-9_-]+")) throw failure("Invalid encoded sync data.");
        try {
            byte[] decoded = Base64.getUrlDecoder().decode(value);
            if (decoded.length > max || !b64(decoded).equals(value)) throw new Exception();
            return decoded;
        } catch (Exception error) { throw failure("Invalid encoded sync data."); }
    }
    private static String utf8(byte[] input) throws Exception {
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(input)).toString();
    }
    private static JSONObject copy(JSONObject input) throws Exception { return new JSONObject(input.toString()); }
    private static Set<String> choices(String... values) { return new HashSet<>(Arrays.asList(values)); }
    private static List<String> names(JSONObject input) {
        ArrayList<String> result = new ArrayList<>(); Iterator<String> keys = input.keys(); while (keys.hasNext()) result.add(keys.next()); return result;
    }
    private static boolean same(Object left, Object right) throws Exception {
        if (left == right) return true;
        if (left == null || right == null) return false;
        if (left instanceof JSONObject && right instanceof JSONObject) {
            JSONObject a = (JSONObject)left, b = (JSONObject)right;
            if (a.length() != b.length()) return false;
            for (String key : names(a)) if (!b.has(key) || !same(a.get(key), b.get(key))) return false;
            return true;
        }
        if (left instanceof JSONArray && right instanceof JSONArray) {
            JSONArray a = (JSONArray)left, b = (JSONArray)right;
            if (a.length() != b.length()) return false;
            for (int i = 0; i < a.length(); i++) if (!same(a.get(i), b.get(i))) return false;
            return true;
        }
        if (left instanceof Number && right instanceof Number)
            return ((Number)left).doubleValue() == ((Number)right).doubleValue();
        return left.equals(right);
    }
    private static IllegalArgumentException failure(String message) { return new IllegalArgumentException(message); }
}
