/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
package org.cyphra.browser;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.SigningInfo;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.net.URL;
import java.net.Socket;
import java.net.InetAddress;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** Manual GitHub updates. A verified download never installs itself. */
public final class UpdateClient {
    public static final String MANIFEST_NAME = "cyphra-android-update.json";
    private static final int MANIFEST_LIMIT = 16384;
    private static final long APK_LIMIT = 512L * 1024 * 1024;
    private static final Pattern VERSION = Pattern.compile("(0|[1-9][0-9]{0,3})\\.(0|[1-9][0-9]{0,3})\\.(0|[1-9][0-9]{0,3})");
    private final Context context;
    private final BrowserStore store;
    private final Config config;
    private final String api;
    private final File directory;
    private final SSLSocketFactory tls = secureSocketFactory();

    public static final class Config {
        public final String edition, repository, keyId, keySPKI, assetPrefix, currentVersion, packageName;
        private final String releasePackageName;
        public final long versionCode;
        public Config(String edition, String repository, String keyId, String keySPKI,
                      String assetPrefix, String currentVersion, long versionCode, String packageName) {
            String expectedRepository = EditionPolicy.repository(edition);
            String expectedPackage = "org.cyphra.browser." + edition;
            boolean allowedDebugPackage = BuildConfig.DEBUG && (expectedPackage + ".debug").equals(packageName);
            if (!expectedRepository.equals(repository) || !EditionPolicy.assetPrefix(edition).equals(assetPrefix)
                || !EditionPolicy.keyId(edition).equals(keyId) || !(expectedPackage.equals(packageName) || allowedDebugPackage)
                || !VERSION.matcher(currentVersion).matches() || versionCode < 1)
                throw new IllegalArgumentException("Invalid Android update configuration.");
            this.edition = edition; this.repository = repository; this.keyId = keyId;
            this.keySPKI = keySPKI; this.assetPrefix = assetPrefix;
            this.currentVersion = currentVersion; this.versionCode = versionCode; this.packageName = packageName;
            this.releasePackageName = expectedPackage;
        }
    }

    /** Metadata is immutable; signed bytes are reverified before each use. */
    public static final class Offer {
        public final String version, published, name, sha256, packageName;
        public final long size, versionCode;
        public final boolean newer;
        private final String envelope, url;
        private Offer(JSONObject manifest, String envelope, String url, boolean newer) throws Exception {
            JSONObject asset = manifest.getJSONObject("assets").getJSONObject("android-universal");
            this.version = manifest.getString("version"); this.published = manifest.getString("published");
            this.packageName = manifest.getString("packageName"); this.versionCode = manifest.getLong("versionCode");
            this.name = asset.getString("name"); this.size = asset.getLong("size"); this.sha256 = asset.getString("sha256");
            this.envelope = envelope; this.url = url; this.newer = newer;
        }
    }

    public UpdateClient(Context context, BrowserStore store, Config config) {
        this.context = context.getApplicationContext(); this.store = store; this.config = config;
        if (!config.edition.equals(store.edition()) || !config.packageName.equals(context.getPackageName()))
            throw new IllegalArgumentException("The updater does not belong to this installation.");
        api = "https://api.github.com/repos/" + config.repository;
        directory = new File(context.getCacheDir(), "updates-" + store.mode());
    }

    public boolean requiresToken() { return "team".equals(config.edition); }
    public boolean hasToken() { return !store.stringPref("github-token-encrypted", "").isEmpty(); }
    public String repository() { return config.repository; }

    /** Accept fine-grained read tokens; do not persist the user's plaintext. */
    public synchronized void configureToken(String value) throws Exception {
        String token = value == null ? "" : value.trim();
        if (!token.matches("github_pat_[A-Za-z0-9_]{20,240}"))
            throw new IllegalArgumentException("Use a fine-grained GitHub token with Contents read access to this repository.");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, credentialKey());
        cipher.updateAAD(credentialBinding());
        byte[] plaintext = token.getBytes(StandardCharsets.UTF_8);
        try {
            JSONObject encrypted = new JSONObject();
            encrypted.put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP));
            encrypted.put("data", Base64.encodeToString(cipher.doFinal(plaintext), Base64.NO_WRAP));
            store.setStringPref("github-token-encrypted", encrypted.toString());
        } finally { Arrays.fill(plaintext, (byte) 0); }
    }

    public synchronized void forgetToken() throws Exception {
        store.removePref("github-token-encrypted");
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore"); keys.load(null);
        if (keys.containsAlias(credentialAlias())) keys.deleteEntry(credentialAlias());
    }

    private String credentialAlias() { return config.packageName + ".github." + store.mode(); }
    private byte[] credentialBinding() {
        return (config.packageName + "\n" + config.repository + "\n" + store.mode()).getBytes(StandardCharsets.UTF_8);
    }
    private SecretKey credentialKey() throws Exception {
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore"); keys.load(null);
        if (!keys.containsAlias(credentialAlias())) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(credentialAlias(), KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).setRandomizedEncryptionRequired(true).build());
            generator.generateKey();
        }
        return (SecretKey) keys.getKey(credentialAlias(), null);
    }
    private synchronized String credential() throws Exception {
        String serialized = store.stringPref("github-token-encrypted", "");
        if (serialized.isEmpty()) {
            if (requiresToken()) throw new IllegalStateException("Add a GitHub token with Contents read access to the private Team repository.");
            return "";
        }
        try {
            if (serialized.length() > 2048) throw new IllegalArgumentException();
            JSONObject encrypted = new JSONObject(serialized);
            byte[] iv = Base64.decode(encrypted.getString("iv"), Base64.DEFAULT);
            byte[] data = Base64.decode(encrypted.getString("data"), Base64.DEFAULT);
            if (iv.length != 12 || data.length > 512) throw new IllegalArgumentException();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, credentialKey(), new GCMParameterSpec(128, iv));
            cipher.updateAAD(credentialBinding());
            byte[] plaintext = cipher.doFinal(data);
            try {
                String token = utf8(plaintext);
                if (!token.matches("github_pat_[A-Za-z0-9_]{20,240}")) throw new IllegalArgumentException();
                return token;
            } finally { Arrays.fill(plaintext, (byte) 0); }
        } catch (Exception error) {
            throw new IllegalStateException("The saved GitHub credential cannot be unlocked. Remove it and add a new token.");
        }
    }

    /** Android tags are independent of desktop releases and GitHub's latest pointer. */
    public synchronized Offer check() throws Exception {
        String token = credential();
        JSONObject selected = null;
        String selectedVersion = null;
        for (int page = 1; page <= 5; page++) {
            String url = api + "/releases?per_page=30&page=" + page;
            JSONArray releases = new JSONArray(utf8(request(url, token, 2 * 1024 * 1024, -1, null, false)));
            if (releases.length() > 30) throw failure("GitHub returned unsupported release metadata.");
            for (int i = 0; i < releases.length(); i++) {
                JSONObject release = releases.getJSONObject(i);
                String tag = release.optString("tag_name");
                if (release.optBoolean("draft", true) || release.optBoolean("prerelease", true) || !tag.startsWith("android-v")) continue;
                String version = tag.substring("android-v".length());
                if (!VERSION.matcher(version).matches()) continue;
                if (selectedVersion == null || compareVersions(version, selectedVersion) > 0) {
                    selected = release; selectedVersion = version;
                }
            }
            if (releases.length() < 30) break;
        }
        if (selected == null) throw failure("No stable Android release is available in this repository.");
        JSONObject manifestAsset = releaseAsset(selected, MANIFEST_NAME, -1, MANIFEST_LIMIT * 2);
        String envelope = utf8(request(manifestAsset.getString("url"), token, MANIFEST_LIMIT * 2, manifestAsset.getLong("size"), null, true));
        JSONObject manifest = verifyManifest(envelope);
        if (!selectedVersion.equals(manifest.getString("version")) || !selected.getString("tag_name").equals(manifest.getString("tag")))
            throw failure("The signed Android release does not match its GitHub tag.");
        JSONObject signedAsset = manifest.getJSONObject("assets").getJSONObject("android-universal");
        JSONObject apk = releaseAsset(selected, signedAsset.getString("name"), signedAsset.getLong("size"), APK_LIMIT);
        int order = compareVersions(manifest.getString("version"), config.currentVersion);
        long code = manifest.getLong("versionCode");
        if ((order > 0 && code <= config.versionCode) || (order == 0 && code != config.versionCode))
            throw failure("The Android release version and update code disagree.");
        return new Offer(manifest, envelope, apk.getString("url"), order > 0 && code > config.versionCode);
    }

    public synchronized File download(Offer offer) throws Exception {
        if (offer == null || !offer.newer) throw failure("A newer verified Android release is required.");
        validateOffer(offer);
        if (!directory.isDirectory() && !directory.mkdirs()) throw failure("The update cache could not be created.");
        File target = new File(directory, offer.name), temporary = new File(directory, offer.name + ".part");
        if (temporary.exists() && !temporary.delete()) throw failure("An old incomplete download could not be removed.");
        try {
            request(offer.url, credential(), APK_LIMIT, offer.size, temporary, true);
            if (!offer.sha256.equals(hash(temporary))) throw failure("The downloaded APK failed its signed SHA-256 check.");
            verifyPackage(temporary, offer);
            if (target.exists() && !target.delete()) throw failure("An old update could not be replaced.");
            if (!temporary.renameTo(target)) throw failure("The verified update could not be saved.");
            verifyForInstall(target, offer);
            return target;
        } catch (Exception error) {
            temporary.delete();
            throw error;
        }
    }

    /** Call immediately before granting the system installer access to the APK. */
    public synchronized void verifyForInstall(File apk, Offer offer) throws Exception {
        validateOffer(offer);
        File expected = new File(directory, offer.name);
        if (!apk.getCanonicalFile().equals(expected.getCanonicalFile()) || !apk.isFile()
            || apk.length() != offer.size || !offer.sha256.equals(hash(apk)))
            throw failure("The saved APK changed after verification. Download it again.");
        verifyPackage(apk, offer);
    }

    private void validateOffer(Offer offer) throws Exception {
        if (offer == null || !offer.newer || !isApiAsset(offer.url)) throw failure("This update was not verified by Cyphra.");
        JSONObject manifest = verifyManifest(offer.envelope);
        JSONObject asset = manifest.getJSONObject("assets").getJSONObject("android-universal");
        if (!manifest.getString("version").equals(offer.version) || manifest.getLong("versionCode") != offer.versionCode
            || !manifest.getString("packageName").equals(offer.packageName) || !asset.getString("name").equals(offer.name)
            || asset.getLong("size") != offer.size || !asset.getString("sha256").equals(offer.sha256)
            || compareVersions(offer.version, config.currentVersion) <= 0 || offer.versionCode <= config.versionCode)
            throw failure("The update metadata failed reverification.");
    }

    private void verifyPackage(File file, Offer offer) throws Exception {
        PackageManager manager = context.getPackageManager();
        PackageInfo installed = manager.getPackageInfo(config.packageName, PackageManager.GET_SIGNING_CERTIFICATES);
        PackageInfo archive = manager.getPackageArchiveInfo(file.getAbsolutePath(), PackageManager.GET_SIGNING_CERTIFICATES);
        if (archive == null || !config.packageName.equals(archive.packageName) || !offer.version.equals(archive.versionName)
            || archive.getLongVersionCode() != offer.versionCode || archive.getLongVersionCode() <= installed.getLongVersionCode()
            || installed.versionName == null || compareVersions(offer.version, installed.versionName) <= 0)
            throw failure("The APK package or version does not match this installation.");
        Set<String> installedSigners = signerHashes(installed.signingInfo), archiveSigners = signerHashes(archive.signingInfo);
        if (installedSigners.isEmpty() || !installedSigners.equals(archiveSigners))
            throw failure("The APK signing certificate does not match the installed Cyphra app.");
    }

    private static Set<String> signerHashes(SigningInfo info) throws Exception {
        Set<String> result = new HashSet<>();
        if (info == null) return result;
        android.content.pm.Signature[] signers = info.getApkContentsSigners();
        if (signers == null || signers.length == 0 || signers.length > 8) return result;
        for (android.content.pm.Signature signer : signers) result.add(hex(MessageDigest.getInstance("SHA-256").digest(signer.toByteArray())));
        return result;
    }

    private JSONObject verifyManifest(String serialized) throws Exception {
        if (serialized == null || serialized.length() > MANIFEST_LIMIT * 2) throw failure("The Android signature envelope exceeds its limit.");
        JSONObject envelope = new JSONObject(serialized);
        exactKeys(envelope, "algorithm", "keyId", "payload", "signature");
        if (!"ECDSA-P256-SHA256".equals(envelope.getString("algorithm")) || !config.keyId.equals(envelope.getString("keyId")))
            throw failure("This Android release uses an untrusted signing key.");
        byte[] payload = base64url(envelope.getString("payload")), raw = base64url(envelope.getString("signature"));
        if (payload.length == 0 || payload.length > MANIFEST_LIMIT || raw.length != 64) throw failure("Invalid Android signature size.");
        PublicKey key = KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(Base64.decode(config.keySPKI, Base64.DEFAULT)));
        Signature verifier = Signature.getInstance("SHA256withECDSA"); verifier.initVerify(key); verifier.update(payload);
        if (!verifier.verify(derSignature(raw))) throw failure("The Android release signature did not verify. Installation was refused.");
        JSONObject manifest = new JSONObject(utf8(payload));
        exactKeys(manifest, "schema", "repository", "edition", "version", "tag", "packageName", "versionCode", "published", "assets");
        String version = manifest.getString("version");
        if (integer(manifest, "schema") != 1 || !config.repository.equals(manifest.getString("repository"))
            || !config.edition.equals(manifest.getString("edition")) || !config.releasePackageName.equals(manifest.getString("packageName"))
            || !VERSION.matcher(version).matches() || !("android-v" + version).equals(manifest.getString("tag"))
            || integer(manifest, "versionCode") < 1 || integer(manifest, "versionCode") > 2100000000L)
            throw failure("The signed Android manifest belongs to another application or edition.");
        try { java.time.Instant.parse(manifest.getString("published")); }
        catch (Exception error) { throw failure("Invalid Android publication timestamp."); }
        JSONObject assets = manifest.getJSONObject("assets"); exactKeys(assets, "android-universal");
        JSONObject asset = assets.getJSONObject("android-universal"); exactKeys(asset, "name", "size", "sha256");
        if (!(config.assetPrefix + "-" + version + "-android-universal.apk").equals(asset.getString("name"))
            || !asset.getString("sha256").matches("[a-f0-9]{64}") || integer(asset, "size") < 1 || integer(asset, "size") > APK_LIMIT)
            throw failure("Invalid signed Android APK metadata.");
        return manifest;
    }

    private JSONObject releaseAsset(JSONObject release, String name, long expectedSize, long limit) throws Exception {
        JSONArray assets = release.getJSONArray("assets");
        if (assets.length() > 100) throw failure("Unsupported GitHub asset metadata.");
        JSONObject match = null;
        for (int i = 0; i < assets.length(); i++) {
            JSONObject asset = assets.getJSONObject(i);
            if (name.equals(asset.optString("name"))) {
                if (match != null) throw failure("The Android release has duplicate assets.");
                match = asset;
            }
        }
        if (match == null) throw failure("The Android release is missing " + name + ".");
        long id = integer(match, "id"), size = integer(match, "size");
        if (id < 1 || id > 9007199254740991L || !"uploaded".equals(match.optString("state")) || size < 1 || size > limit
            || expectedSize >= 0 && size != expectedSize || !(api + "/releases/assets/" + id).equals(match.getString("url")))
            throw failure("GitHub's Android asset metadata failed validation.");
        return match;
    }

    private boolean isApiAsset(String value) {
        return value != null && value.matches(Pattern.quote(api) + "/releases/assets/[1-9][0-9]{0,15}");
    }
    private boolean isApiRequest(String value) {
        return isApiAsset(value) || value != null && value.matches(Pattern.quote(api) + "/releases\\?per_page=30&page=[1-5]");
    }
    private static boolean isAssetRedirect(String value) {
        try {
            URI uri = new URI(value);
            return value.length() <= 16384 && "https".equals(uri.getScheme()) && "release-assets.githubusercontent.com".equals(uri.getHost())
                && uri.getPort() == -1 && uri.getRawUserInfo() == null && uri.getRawFragment() == null
                && uri.getRawPath().matches("/github-production-release-asset/[^/]+/[^/]+")
                && !uri.getRawPath().contains("\\") && !uri.getRawPath().toLowerCase(java.util.Locale.ROOT).contains("%2f");
        } catch (Exception error) { return false; }
    }

    /** Authorization is set only on the initial repository API connection. */
    private byte[] request(String initial, String token, long limit, long expectedSize, File target, boolean allowRedirect) throws Exception {
        if (!isApiRequest(initial)) throw failure("The updater refused an untrusted API URL.");
        String current = initial;
        Set<String> visited = new HashSet<>();
        long deadline = android.os.SystemClock.elapsedRealtime() + (target == null ? 60000 : 15 * 60000);
        for (int redirects = 0; redirects <= 3; redirects++) {
            if (!visited.add(current)) throw failure("The updater refused a redirect loop.");
            HttpsURLConnection connection = (HttpsURLConnection) new URL(current).openConnection();
            connection.setSSLSocketFactory(tls);
            connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(15000); connection.setReadTimeout(30000);
            connection.setUseCaches(false); connection.setRequestProperty("Cache-Control", "no-store");
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.setRequestProperty("User-Agent", "Cyphra-Android-Update/" + config.currentVersion);
            connection.setRequestProperty("Accept", isApiAsset(initial) ? "application/octet-stream" : "application/vnd.github+json");
            if (redirects == 0) {
                connection.setRequestProperty("X-GitHub-Api-Version", "2026-03-10");
                if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);
            }
            try {
                int status = connection.getResponseCode();
                if (status == 301 || status == 302 || status == 303 || status == 307 || status == 308) {
                    String next = connection.getHeaderField("Location");
                    if (!allowRedirect || redirects == 3 || !isAssetRedirect(next)) throw failure("The updater refused an unexpected download redirect.");
                    current = next;
                    continue;
                }
                if (status != 200) throw failure(status == 401 || status == 403 || status == 404
                    ? (requiresToken() ? "GitHub access failed. Check the token's Contents read access to the Team repository." : "GitHub could not retrieve this Android release.")
                    : "GitHub returned HTTP " + status + ".");
                long length = connection.getContentLengthLong();
                if (length > limit || expectedSize >= 0 && length >= 0 && length != expectedSize) throw failure("The update response has an unexpected size.");
                ByteArrayOutputStream memory = target == null ? new ByteArrayOutputStream() : null;
                try (InputStream input = connection.getInputStream(); FileOutputStream output = target == null ? null : new FileOutputStream(target)) {
                    byte[] buffer = new byte[65536]; long count = 0; int read;
                    while ((read = input.read(buffer)) != -1) {
                        if (Thread.currentThread().isInterrupted() || android.os.SystemClock.elapsedRealtime() > deadline) throw failure("The update download was cancelled or timed out.");
                        count += read;
                        if (count > limit || expectedSize >= 0 && count > expectedSize) throw failure("The update response exceeds its signed size.");
                        if (output == null) memory.write(buffer, 0, read); else output.write(buffer, 0, read);
                    }
                    if (expectedSize >= 0 && count != expectedSize) throw failure("The update download is incomplete.");
                    if (output != null) { output.flush(); output.getFD().sync(); }
                    return memory == null ? new byte[0] : memory.toByteArray();
                }
            } finally { connection.disconnect(); }
        }
        throw failure("The download exceeded its redirect limit.");
    }

    public static int compareVersions(String left, String right) {
        if (left == null || right == null || !VERSION.matcher(left).matches() || !VERSION.matcher(right).matches())
            throw new IllegalArgumentException("Invalid Android release version.");
        String[] a = left.split("\\."), b = right.split("\\.");
        for (int i = 0; i < 3; i++) {
            int result = Integer.compare(Integer.parseInt(a[i]), Integer.parseInt(b[i]));
            if (result != 0) return result;
        }
        return 0;
    }
    private static void exactKeys(JSONObject value, String... names) throws Exception {
        if (value.length() != names.length) throw failure("Unsupported signed Android manifest fields.");
        for (String name : names) if (!value.has(name)) throw failure("Missing signed Android manifest fields.");
    }
    private static long integer(JSONObject value, String name) throws Exception {
        Object number = value.get(name);
        if (!(number instanceof Integer) && !(number instanceof Long)) throw failure("Invalid integer in Android release metadata.");
        return ((Number) number).longValue();
    }
    private static byte[] base64url(String input) throws Exception {
        if (input == null || !input.matches("[A-Za-z0-9_-]+") || input.length() % 4 == 1)
            throw failure("Invalid Android signature encoding.");
        return Base64.decode(input, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }
    private static String utf8(byte[] bytes) throws Exception {
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
    }
    /** Java's verifier uses ASN.1 DER, while Cyphra's envelope uses raw r||s. */
    private static byte[] derSignature(byte[] raw) throws Exception {
        if (raw.length != 64) throw failure("Invalid P-256 signature.");
        byte[] r = derInteger(Arrays.copyOfRange(raw, 0, 32)), s = derInteger(Arrays.copyOfRange(raw, 32, 64));
        ByteArrayOutputStream der = new ByteArrayOutputStream();
        der.write(0x30); der.write(r.length + s.length + 4); der.write(0x02); der.write(r.length); der.write(r);
        der.write(0x02); der.write(s.length); der.write(s); return der.toByteArray();
    }
    private static byte[] derInteger(byte[] input) {
        int first = 0; while (first < input.length - 1 && input[first] == 0) first++;
        byte[] value = Arrays.copyOfRange(input, first, input.length);
        if ((value[0] & 0x80) == 0) return value;
        byte[] positive = new byte[value.length + 1]; System.arraycopy(value, 0, positive, 1, value.length); return positive;
    }
    private static String hash(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return hex(digest.digest());
    }
    private static String hex(byte[] input) {
        StringBuilder result = new StringBuilder(input.length * 2);
        for (byte value : input) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }
    private static IllegalStateException failure(String message) { return new IllegalStateException(message); }
    static SSLSocketFactory secureSocketFactory() { return new ModernTLSFactory(HttpsURLConnection.getDefaultSSLSocketFactory()); }

    /** Keep system certificate/hostname checks, but never negotiate legacy TLS. */
    private static final class ModernTLSFactory extends SSLSocketFactory {
        private final SSLSocketFactory delegate;
        ModernTLSFactory(SSLSocketFactory delegate) { this.delegate = delegate; }
        private Socket secure(Socket value) throws IOException {
            if (!(value instanceof SSLSocket)) throw new IOException("A secure TLS socket is required.");
            SSLSocket socket = (SSLSocket) value;
            String[] protocols = Arrays.stream(socket.getSupportedProtocols())
                .filter(name -> "TLSv1.3".equals(name) || "TLSv1.2".equals(name)).toArray(String[]::new);
            String[] suites = modernSuites(socket.getEnabledCipherSuites());
            if (protocols.length == 0 || suites.length == 0) throw new IOException("TLS 1.2 or newer with AEAD is required.");
            socket.setEnabledProtocols(protocols); socket.setEnabledCipherSuites(suites); return socket;
        }
        private static String[] modernSuites(String[] input) {
            return Arrays.stream(input).filter(name -> name.startsWith("TLS_")
                && (name.contains("_GCM_") || name.contains("_CHACHA20_")))
                .filter(name -> name.startsWith("TLS_AES_") || name.startsWith("TLS_CHACHA20_")
                    || name.startsWith("TLS_ECDHE_") || name.startsWith("TLS_DHE_")).toArray(String[]::new);
        }
        @Override public String[] getDefaultCipherSuites() { return modernSuites(delegate.getDefaultCipherSuites()); }
        @Override public String[] getSupportedCipherSuites() { return modernSuites(delegate.getSupportedCipherSuites()); }
        @Override public Socket createSocket() throws IOException { return secure(delegate.createSocket()); }
        @Override public Socket createSocket(Socket socket, String host, int port, boolean close) throws IOException { return secure(delegate.createSocket(socket, host, port, close)); }
        @Override public Socket createSocket(String host, int port) throws IOException { return secure(delegate.createSocket(host, port)); }
        @Override public Socket createSocket(String host, int port, InetAddress local, int localPort) throws IOException { return secure(delegate.createSocket(host, port, local, localPort)); }
        @Override public Socket createSocket(InetAddress host, int port) throws IOException { return secure(delegate.createSocket(host, port)); }
        @Override public Socket createSocket(InetAddress host, int port, InetAddress local, int localPort) throws IOException { return secure(delegate.createSocket(host, port, local, localPort)); }
    }
}
