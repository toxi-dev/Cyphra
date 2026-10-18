/* MPL-2.0. Native qualification helpers; excluded from release APKs. */
package org.cyphra.browser;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Called on the native qualification runner's worker thread. */
public final class SyncNativeChecks {
    private static final String CONFIG = "sync-config-encrypted-v2", STATE = "sync-state-v2", LABEL = "sync-server-label-v2";
    private static final String SECRET = "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc";
    private static final String VAULT = "11111111111111111111111111111111";
    private static Object invoke(SyncClient client, String method, Class<?>[] types, Object... arguments) throws Exception {
        Method m = SyncClient.class.getDeclaredMethod(method, types); m.setAccessible(true);
        try { return m.invoke(client, arguments); }
        catch (InvocationTargetException failure) {
            if (failure.getCause() instanceof Exception) throw (Exception)failure.getCause();
            throw failure;
        }
    }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private interface Operation { void run() throws Exception; }
    private static void rejects(Operation operation, String message) throws Exception {
        try { operation.run(); } catch (Exception expected) { return; }
        throw new AssertionError(message);
    }
    private static void restore(SharedPreferences data, Map<String, ?> original) {
        SharedPreferences.Editor edit = data.edit();
        for (String key : new String[]{"bookmarks", "save-history", CONFIG, STATE, LABEL}) {
            Object value = original.get(key);
            if (value instanceof String) edit.putString(key, (String)value);
            else if (value instanceof Boolean) edit.putBoolean(key, (Boolean)value);
            else edit.remove(key);
        }
        check(edit.commit(), "Could not restore the qualification fixture's local settings.");
    }
    private static JSONObject scope(String mode) throws Exception {
        return new JSONObject().put("edition", BuildConfig.EDITION).put("mode", mode);
    }

    public static JSONObject run(Context context) throws Exception {
        String mode=BuildConfig.HOME?"personal":"work";
        BrowserStore store = new BrowserStore(context, mode, BuildConfig.EDITION);
        SyncClient client = new SyncClient(context, store);
        SharedPreferences data = context.getSharedPreferences("cyphra-data-"+mode, Context.MODE_PRIVATE);
        Map<String, ?> original = data.getAll();
        check(!client.isPaired(), "Use a disposable unpaired profile for native sync qualification.");
        JSONArray checks = new JSONArray();
        try {
            store.setStringPref("bookmarks", "[]"); store.setBooleanPref("save-history", false);
            store.addBookmark("Local test bookmark", "https://example.org/local");
            JSONObject initial = (JSONObject)invoke(client, "newState", new Class<?>[0]);
            JSONObject snapshot = (JSONObject)invoke(client, "snapshot", new Class<?>[0]);
            JSONObject captured = (JSONObject)invoke(client, "capture", new Class<?>[]{JSONObject.class, JSONObject.class}, initial, snapshot);
            JSONObject records = captured.getJSONObject("records");
            String bookmark = null;
            for (java.util.Iterator<String> keys = records.keys(); keys.hasNext();) {
                String key = keys.next(); if (key.startsWith("b:")) bookmark = key;
                check(key.startsWith("b:") || key.equals("p:places.history.enabled"), "History/cookies/credentials entered sync records.");
            }
            check(bookmark != null && records.length() == 2, "Actual local bookmark was not captured.");
            String localGuid = bookmark;
            checks.put("Actual local HTTP bookmark receives a stable desktop-compatible GUID");
            JSONObject again = (JSONObject)invoke(client, "capture", new Class<?>[]{JSONObject.class, JSONObject.class}, captured, snapshot);
            check(again.getJSONObject("records").has(localGuid), "An unchanged bookmark lost its GUID.");
            JSONObject folder = new JSONObject().put("clock", 4).put("device", "33333333333333333333333333333333").put("deleted", false)
                .put("value", new JSONObject().put("guid", "folder000001").put("parentGuid", "toolbar_____").put("type", 2).put("title", "Desktop folder").put("index", 0));
            again.getJSONObject("records").put("b:folder000001", folder);
            again.getJSONObject("records").put("s:https://example.org", new JSONObject().put("clock", 5)
                .put("device", "33333333333333333333333333333333").put("deleted", false).put("value", "strict"));
            JSONObject afterOpaque = (JSONObject)invoke(client, "capture", new Class<?>[]{JSONObject.class, JSONObject.class}, again, snapshot);
            check(!afterOpaque.getJSONObject("records").getJSONObject("b:folder000001").getBoolean("deleted")
                && !afterOpaque.getJSONObject("records").getJSONObject("s:https://example.org").getBoolean("deleted"), "An unsupported desktop record was erased.");
            checks.put("Desktop folders and Shield exceptions survive an Android capture");
            store.removeBookmark("https://example.org/local");
            JSONObject deleted = (JSONObject)invoke(client, "capture", new Class<?>[]{JSONObject.class, JSONObject.class}, afterOpaque,
                (JSONObject)invoke(client, "snapshot", new Class<?>[0]));
            check(deleted.getJSONObject("records").getJSONObject(localGuid).getBoolean("deleted"), "Actual local deletion did not become a tombstone.");
            check(!deleted.getJSONObject("records").getJSONObject("b:folder000001").getBoolean("deleted"), "A local URL deletion erased a desktop folder.");
            checks.put("Removing a displayed bookmark creates its tombstone without deleting desktop-only items");
            SyncClient.Keys keys = SyncClient.keys(SECRET);
            check(keys.token.equals("fbPdYI9WiiXGyLxsqcaAD7TamYE1fpxi6B0TqRw45W0"), "Native HKDF/HMAC differs from desktop WebCrypto.");
            JSONObject envelope = SyncClient.encryptPayload(deleted, SECRET, VAULT);
            JSONObject plaintext = SyncClient.decryptPayload(envelope, SECRET, VAULT);
            SyncClient.assertPayloadScope(plaintext, scope(mode));
            check(!envelope.toString().contains("example.org"), "Plaintext entered a sync envelope.");
            rejects(() -> SyncClient.decryptPayload(envelope, SECRET, "44444444444444444444444444444444"), "Wrong-vault AAD was accepted.");
            checks.put("Native AES-GCM/HKDF/HMAC authenticates vault identity and matches desktop token");
            String foreign = "cyphra-sync-v2.aHR0cHM6Ly9leGFtcGxlLm9yZw." + VAULT + "." + SECRET + "." + (BuildConfig.HOME?"public":BuildConfig.EDITION) + ".personal";
            try { client.pair("https://example.org", foreign); throw new AssertionError("Foreign-mode code was accepted."); }
            catch (IllegalArgumentException expected) { check(expected.getMessage().contains("different Cyphra edition or mode"), "Pairing attempted a request before checking mode binding."); }
            checks.put(BuildConfig.HOME?"Foreign edition is rejected before any server request":"Foreign Work/Personal binding is rejected before any server request");
            JSONObject configuration = (JSONObject)invoke(client, "configuration", new Class<?>[]{String.class, String.class, String.class, long.class},
                "https://example.org", VAULT, SECRET, 1L);
            invoke(client, "commitConfiguration", new Class<?>[]{JSONObject.class, JSONObject.class}, configuration, deleted);
            String encrypted = data.getString(CONFIG, "");
            check(client.isPaired() && !encrypted.contains(SECRET) && !encrypted.contains(VAULT), "Device vault credentials were stored as plaintext.");
            JSONObject unlocked = (JSONObject)invoke(client, "readConfiguration", new Class<?>[0]);
            check(unlocked.getString("secret").equals(SECRET), "Actual Android Keystore could not unwrap its saved configuration.");
            checks.put("Actual Android Keystore encrypts and unwraps mode-bound vault credentials");
            BrowserStore foreignStore = new BrowserStore(context, mode, BuildConfig.TEAM ? "public" : "team");
            SyncClient foreignClient = new SyncClient(context, foreignStore);
            rejects(() -> invoke(foreignClient, "readConfiguration", new Class<?>[0]), "Copied credentials were accepted by another edition.");
            checks.put("Keystore alias and authenticated configuration refuse copied foreign-edition credentials");
            String bookmarks = data.getString("bookmarks", "[]"); client.disconnect();
            check(!client.isPaired() && data.getString("bookmarks", "[]").equals(bookmarks), "Disconnect removed local bookmarks.");
            KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore"); keyStore.load(null);
            check(!keyStore.containsAlias(context.getPackageName() + ".sync.v2." + BuildConfig.EDITION + "."+mode), "Disconnect left its fixture wrapping key.");
            checks.put("Disconnect removes vault configuration and its wrapping key while preserving local bookmarks");
            return new JSONObject().put("passed", true).put("edition", BuildConfig.EDITION).put("mode", mode).put("checks", checks);
        } finally { client.disconnect(); restore(data, original); }
    }

    /** The pairing code is supplied at runtime in an app-private disposable file. */
    public static JSONObject network(Context context, JSONObject fixture) throws Exception {
        String mode = fixture.getString("mode");
        check(fixture.getString("edition").equals(BuildConfig.EDITION), "The HTTPS fixture belongs to another edition.");
        BrowserStore store = new BrowserStore(context, mode, BuildConfig.EDITION);
        SyncClient client = new SyncClient(context, store);
        SharedPreferences data = context.getSharedPreferences("cyphra-data-" + mode, Context.MODE_PRIVATE);
        Map<String, ?> original = data.getAll();
        check(!client.isPaired(), "Use a disposable unpaired profile for HTTPS sync qualification.");
        JSONArray checks = new JSONArray();
        try {
            store.setStringPref("bookmarks", "[]");
            client.pair(fixture.getString("endpoint"), fixture.getString("pairingCode"));
            check(client.isPaired(), "The native client did not authenticate and save the actual HTTPS vault.");
            SyncClient.Result imported = client.sync();
            check(store.hasBookmark(fixture.getString("remoteURL")) && store.hasBookmark(fixture.getString("deletedURL")), "Desktop HTTP bookmarks did not import through the actual HTTPS vault.");
            check(!store.booleanPref("save-history", true), "The selected history-saving preference did not import.");
            checks.put("Actual HTTPS vault created by desktop WebCrypto pairs and imports its bookmarks and selected preference");
            store.removeBookmark(fixture.getString("deletedURL"));
            store.addBookmark(fixture.getString("localTitle"), fixture.getString("localURL"));
            SyncClient.Result exported = client.sync();
            check(!store.hasBookmark(fixture.getString("deletedURL")) && store.hasBookmark(fixture.getString("localURL")), "The local tombstone/addition was not preserved after the HTTPS merge.");
            checks.put("A real Android bookmark addition and deletion complete optimistic authenticated HTTPS synchronization");
            check(exported.revision > imported.revision, "The real server revision did not advance.");
            String serialized = data.getString(STATE, ""); JSONObject state = new JSONObject(serialized);
            check(state.getJSONObject("records").getJSONObject("b:bookmark0002").getBoolean("deleted"), "The desktop bookmark GUID did not receive its actual deletion tombstone.");
            check(state.getJSONObject("records").has("b:folder000001") && state.getJSONObject("records").has("s:https://example.org"), "Desktop-only records disappeared from the real merged vault.");
            checks.put("Real merged state retains desktop folder/Shield records and the exact deleted bookmark GUID");
            return new JSONObject().put("passed", true).put("edition", BuildConfig.EDITION).put("mode", mode)
                .put("revision", exported.revision).put("bookmarks", exported.bookmarks).put("checks", checks);
        } finally { client.disconnect(); restore(data, original); }
    }
}
