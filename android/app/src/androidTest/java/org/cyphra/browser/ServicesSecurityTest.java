/* MPL-2.0. Runs platform crypto, mode storage and APK policy on an Android VM. */
package org.cyphra.browser;

import android.content.Context;
import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.RandomAccessFile;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

public final class ServicesSecurityTest extends Instrumentation {
    private Context target;
    private Bundle arguments;
    @Override public void onCreate(Bundle arguments) {
        this.arguments = arguments == null ? new Bundle() : new Bundle(arguments);
        super.onCreate(arguments); start();
    }
    @Override public void onStart() {
        JSONArray checks = new JSONArray();
        JSONObject proof = new JSONObject();
        try {
            nativeCheck("mode-bound bookmarks, tabs and history", this::testModeBoundBookmarksTabsAndHistory, checks);
            nativeCheck("ordinary tab selection, native home and legacy session compatibility", this::testOrdinaryTabSelectionAndLegacySessionStorage, checks);
            nativeCheck("appearance reset preserves protected profile data and other mode", this::testAppearanceResetKeepsProfileData, checks);
            nativeCheck("Android permission results stay bound to their original website request", this::testAndroidPermissionCallbacksStayBound, checks);
            nativeCheck("pinned P-256 manifest, tamper and cross-edition refusal", this::testPinnedSignedManifestAndCrossEditionRefusal, checks);
            nativeCheck("repository API and GitHub asset CDN allowlists", this::testOnlyRepositoryApiAndGitHubAssetCdnAllowed, checks);
            nativeCheck("Android Keystore credentials encrypted and bound to mode", this::testCredentialsAreEncryptedAndBoundToMode, checks);
            nativeCheck("APK cache boundary, signed size, hash and package refusal", this::testSavedApkMustPassEveryInstallCheck, checks);
            nativeCheck("TLS 1.2/1.3 and forward-secret AEAD protocols only", this::testModernTlsProtocolsAndCiphers, checks);
            proof.put("passed", true); proof.put("edition", BuildConfig.EDITION);
            proof.put("packageName", getTargetContext().getPackageName()); proof.put("checks", checks);
            proof.put("sync", SyncNativeChecks.run(target));
            if ("true".equals(arguments.getString("updaterNetwork", "false"))) {
                proof.put("githubUpdate", testRealPublishedGitHubUpdate());
            }
            String fixturePath = arguments.getString("syncFixture", "");
            if (!fixturePath.isEmpty()) {
                File fixture = new File(fixturePath).getCanonicalFile();
                File cache = target.getCacheDir().getCanonicalFile();
                if (!fixture.getParentFile().equals(cache) || !fixture.isFile() || fixture.length() > 32768)
                    throw new IllegalStateException("The native sync fixture must be a bounded file in app-private cache.");
                JSONObject networkFixture;
                try (java.io.FileInputStream input = new java.io.FileInputStream(fixture)) {
                    ByteArrayOutputStream contents = new ByteArrayOutputStream(); byte[] buffer = new byte[4096]; int count;
                    while ((count = input.read(buffer)) != -1) contents.write(buffer, 0, count);
                    networkFixture = new JSONObject(contents.toString(StandardCharsets.UTF_8.name()));
                }
                try { proof.put("syncNetwork", SyncNativeChecks.network(target, networkFixture)); }
                finally { fixture.delete(); }
            }
            Bundle result = new Bundle(); result.putString("stream", "\n" + proof.toString() + "\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            Bundle result = new Bundle();
            result.putString("stream", "\nNative services test failed: " + error.getClass().getSimpleName() + ": " + error.getMessage() + "\n");
            finish(Activity.RESULT_CANCELED, result);
        }
    }
    private void nativeCheck(String name, RunnableChecked action, JSONArray checks) throws Exception {
        setUp();
        try { action.run(); checks.put(name); }
        finally { clearFiles(); }
    }
    private void setUp() throws Exception {
        target = getTargetContext();
        clearFiles();
    }
    private void clearFiles() {
        if (target == null) return;
        for (String mode : new String[]{"work", "personal"}) {
            BrowserStore store = new BrowserStore(target, mode, BuildConfig.EDITION);
            try { new UpdateClient(target, store, config()).forgetToken(); } catch (Exception ignored) {}
            target.getSharedPreferences("cyphra-data-" + mode, Context.MODE_PRIVATE).edit().clear().commit();
        }
    }
    private UpdateClient.Config config() {
        try {
            android.content.pm.PackageInfo installed=target.getPackageManager().getPackageInfo(target.getPackageName(),0);
            return new UpdateClient.Config(BuildConfig.EDITION, BuildConfig.REPOSITORY, BuildConfig.UPDATE_KEY_ID,
                BuildConfig.UPDATE_KEY_SPKI, BuildConfig.ASSET_PREFIX, installed.versionName, installed.getLongVersionCode(), target.getPackageName());
        } catch(android.content.pm.PackageManager.NameNotFoundException error) {throw new IllegalStateException(error);}
    }
    private UpdateClient updater(String mode) { return new UpdateClient(target, new BrowserStore(target, mode, BuildConfig.EDITION), config()); }
    private String fixture(String edition) throws Exception {
        return fixtureFile("updater-valid-" + edition + ".json");
    }
    private String fixtureFile(String name) throws Exception {
        try (InputStream input = getContext().getAssets().open(name)) {
            ByteArrayOutputStream result = new ByteArrayOutputStream(); byte[] buffer = new byte[4096]; int count;
            while ((count = input.read(buffer)) != -1) result.write(buffer, 0, count);
            return result.toString(StandardCharsets.UTF_8.name());
        }
    }
    private Object invoke(Object instance, String method, Class<?>[] types, Object... arguments) throws Exception {
        Method target = instance.getClass().getDeclaredMethod(method, types); target.setAccessible(true);
        try { return target.invoke(instance, arguments); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof Exception) throw (Exception) error.getCause();
            throw error;
        }
    }
    private void rejects(RunnableChecked action) throws Exception {
        try { action.run(); fail("Security policy accepted an invalid value."); }
        catch (IllegalStateException | IllegalArgumentException expected) {}
    }
    private void rejectsWithMessage(String message,RunnableChecked action) throws Exception {
        try { action.run(); fail("Security policy accepted an invalid value."); }
        catch (IllegalStateException expected) { assertEquals(message,expected.getMessage()); }
    }
    private interface RunnableChecked { void run() throws Exception; }
    private static void fail(String message) { throw new AssertionError(message); }
    private static void assertTrue(boolean value) { if (!value) fail("Expected true."); }
    private static void assertFalse(boolean value) { if (value) fail("Expected false."); }
    private static void assertEquals(Object expected, Object actual) {
        if (!java.util.Objects.equals(expected, actual)) fail("Expected " + expected + ", got " + actual + ".");
    }

    public void testModeBoundBookmarksTabsAndHistory() throws Exception {
        BrowserStore work = new BrowserStore(target, "work", BuildConfig.EDITION);
        BrowserStore personal = new BrowserStore(target, "personal", BuildConfig.EDITION);
        work.addBookmark("Internal", "https://example.org/work");
        personal.addBookmark("Personal", "https://example.org/personal");
        assertEquals(1, work.bookmarks().length()); assertEquals(1, personal.bookmarks().length());
        assertFalse(personal.hasBookmark("https://example.org/work"));
        work.recordVisit("Sensitive", "https://example.org/work");
        personal.recordVisit("Personal", "https://example.org/personal");
        assertEquals(0, work.history().length()); assertEquals(1, personal.history().length());
        work.setBooleanPref("save-history", true); work.recordVisit("Opted in", "https://example.org/work");
        assertEquals(1, work.history().length());
        work.saveTabs(new JSONArray().put("https://example.org/work").put("javascript:alert(1)").put("file:///tmp/a").put("about:blank"));
        assertEquals(2, work.tabs().length()); assertEquals(0, personal.tabs().length());
        work.removeBookmark("https://example.org/work"); assertEquals(0, work.bookmarks().length());
        personal.clearHistory(); assertEquals(0, personal.history().length());
        rejects(() -> new BrowserStore(target, "other", BuildConfig.EDITION));
        rejects(() -> work.addBookmark("Script", "javascript:alert(1)"));
    }

    public void testOrdinaryTabSelectionAndLegacySessionStorage() throws Exception {
        BrowserStore store = new BrowserStore(target, "work", BuildConfig.EDITION);
        // Existing releases stored either URL strings or title/URL objects,
        // without a selected-tab preference. They still open the first tab.
        target.getSharedPreferences("cyphra-data-work", Context.MODE_PRIVATE).edit()
            .putString("tabs", new JSONArray().put("https://example.org/legacy")
                .put(new JSONObject().put("url", "about:blank").put("title", "New tab")).toString())
            .remove("tabs-selected").commit();
        assertEquals(2, store.tabs().length()); assertEquals(0, store.selectedTab());

        JSONArray input = new JSONArray()
            .put(new JSONObject().put("url", "https://example.org/first").put("title", "First"))
            .put("javascript:alert(1)")
            .put(new JSONObject().put("url", "https://example.org/private").put("private", true))
            .put(new JSONObject().put("url", "about:blank").put("title", "New tab"))
            .put("https://example.org/last");
        store.saveTabs(input, 3);
        BrowserStore reopened = new BrowserStore(target, "work", BuildConfig.EDITION);
        assertEquals(3, reopened.tabs().length()); assertEquals(1, reopened.selectedTab());
        assertEquals("about:blank", reopened.tabs().getJSONObject(reopened.selectedTab()).getString("url"));
        assertFalse(reopened.tabs().toString().contains("example.org/private"));
        assertEquals(0, new BrowserStore(target, "personal", BuildConfig.EDITION).tabs().length());

        store.saveTabs(input, 999); assertEquals(2, store.selectedTab());
        store.saveTabs(input, -1); assertEquals(0, store.selectedTab());
        store.saveTabs(new JSONArray(), 4); assertEquals(0, store.tabs().length()); assertEquals(0, store.selectedTab());
    }

    public void testAppearanceResetKeepsProfileData() throws Exception {
        BrowserStore work=new BrowserStore(target,"work",BuildConfig.EDITION);
        BrowserStore personal=new BrowserStore(target,"personal",BuildConfig.EDITION);
        work.addBookmark("Retained bookmark","https://example.org/retained");
        work.saveTabs(new JSONArray().put("about:blank").put("https://example.org/retained"),1);
        work.setStringPref("sync-config-encrypted-v2","opaque-profile-bound-fixture");
        work.setBooleanPref("save-history",false);
        updater("work").configureToken("github_pat_fixturefixturefixturefixturefixturefixturefixturefixture");
        java.util.Map<String,?> before=new java.util.HashMap<>(target.getSharedPreferences("cyphra-data-work",Context.MODE_PRIVATE).getAll());
        java.util.Map<String,?> engineBefore=new java.util.HashMap<>(target.getSharedPreferences("cyphra-engine-work",Context.MODE_PRIVATE).getAll());
        personal.setStringPref(Appearance.PREFIX+"theme","light");
        work.setStringPref(Appearance.PREFIX+"theme","black");
        work.setStringPref(Appearance.PREFIX+"text-scale","125");
        assertFalse(new Appearance(target,work).light);
        assertTrue(new Appearance(target,personal).light);
        Appearance.reset(work);
        assertEquals(before,target.getSharedPreferences("cyphra-data-work",Context.MODE_PRIVATE).getAll());
        assertEquals(engineBefore,target.getSharedPreferences("cyphra-engine-work",Context.MODE_PRIVATE).getAll());
        assertEquals("light",new Appearance(target,personal).theme);
        assertEquals("graphite",new Appearance(target,work).theme);
        assertEquals("100",new Appearance(target,work).scaleChoice);
        assertTrue(updater("work").hasToken());
        work.setStringPref(Appearance.PREFIX+"theme","not-a-theme");
        work.setStringPref(Appearance.PREFIX+"text-scale","1000000");
        assertEquals("graphite",new Appearance(target,work).theme);
        assertEquals("100",new Appearance(target,work).scaleChoice);
    }

    public void testAndroidPermissionCallbacksStayBound() throws Exception {
        Throwable[] failure={null};
        runOnMainSync(()->{try{checkAndroidPermissionCallbacksStayBound();}catch(Throwable error){failure[0]=error;}});
        if(failure[0] instanceof Exception)throw (Exception)failure[0];
        if(failure[0]!=null)throw new AssertionError("Native permission callback check failed.",failure[0]);
    }
    private void checkAndroidPermissionCallbacksStayBound() throws Exception {
        String denied=null;
        for(String permission:new String[]{android.Manifest.permission.CAMERA,android.Manifest.permission.RECORD_AUDIO,
            android.Manifest.permission.ACCESS_FINE_LOCATION,android.Manifest.permission.ACCESS_COARSE_LOCATION})
            if(target.checkSelfPermission(permission)!=android.content.pm.PackageManager.PERMISSION_GRANTED){denied=permission;break;}
        if(denied==null)fail("Permission checks require one denied runtime permission in the disposable test profile.");
        WebPrompts prompts=new WebPrompts(new PermissionTestActivity(target),new Appearance(target,new BrowserStore(target,"work",BuildConfig.EDITION)),session->"https://example.org/");
        PermissionDecision original=new PermissionDecision(),overlap=new PermissionDecision();
        seedPermissionRequest(prompts,original,denied);
        prompts.onAndroidPermissionsRequest(null,new String[]{denied},overlap);
        assertEquals(1,overlap.rejections);assertEquals(0,overlap.grants);
        assertTrue(permissionField(prompts,"permissionCallback")==original);
        assertEquals(0,original.rejections);assertEquals(0,original.grants);

        prompts.dismissPending();
        assertEquals(1,original.rejections);assertTrue((Boolean)permissionField(prompts,"androidPermissionInFlight"));
        PermissionDecision nextPage=new PermissionDecision();
        prompts.onAndroidPermissionsRequest(null,new String[]{denied},nextPage);
        assertEquals(1,nextPage.rejections);assertEquals(0,nextPage.grants);
        prompts.onRequestPermissionsResult(72,new int[]{android.content.pm.PackageManager.PERMISSION_GRANTED});
        assertEquals(0,original.grants);assertEquals(0,nextPage.grants);
        assertFalse((Boolean)permissionField(prompts,"androidPermissionInFlight"));
        assertEquals(null,permissionField(prompts,"permissionCallback"));assertEquals(null,permissionField(prompts,"requestedAndroidPermissions"));

        PermissionDecision forgedResult=new PermissionDecision();
        seedPermissionRequest(prompts,forgedResult,denied);
        prompts.onRequestPermissionsResult(71,new int[]{android.content.pm.PackageManager.PERMISSION_GRANTED});
        assertTrue(permissionField(prompts,"permissionCallback")==forgedResult);
        prompts.onRequestPermissionsResult(72,new int[]{android.content.pm.PackageManager.PERMISSION_GRANTED});
        assertEquals(1,forgedResult.rejections);assertEquals(0,forgedResult.grants);
        assertFalse((Boolean)permissionField(prompts,"androidPermissionInFlight"));

        PermissionDecision emptyResult=new PermissionDecision();
        seedPermissionRequest(prompts,emptyResult,denied);
        prompts.onRequestPermissionsResult(72,new int[0]);
        assertEquals(1,emptyResult.rejections);assertEquals(0,emptyResult.grants);
    }
    private static final class PermissionTestActivity extends Activity {
        PermissionTestActivity(Context context){attachBaseContext(context);}
    }
    private static final class PermissionDecision implements org.mozilla.geckoview.GeckoSession.PermissionDelegate.Callback {
        int grants,rejections;
        @Override public void grant(){grants++;}
        @Override public void reject(){rejections++;}
    }
    private static Object permissionField(WebPrompts prompts,String name) throws Exception {
        java.lang.reflect.Field field=WebPrompts.class.getDeclaredField(name);field.setAccessible(true);return field.get(prompts);
    }
    private static void seedPermissionRequest(WebPrompts prompts,PermissionDecision decision,String permission) throws Exception {
        for(String name:new String[]{"permissionCallback","requestedAndroidPermissions","androidPermissionInFlight"}){
            java.lang.reflect.Field field=WebPrompts.class.getDeclaredField(name);field.setAccessible(true);
            field.set(prompts,"permissionCallback".equals(name)?decision:"requestedAndroidPermissions".equals(name)?new String[]{permission}:true);
        }
    }

    public void testPinnedSignedManifestAndCrossEditionRefusal() throws Exception {
        UpdateClient client = updater("work");
        JSONObject valid = (JSONObject) invoke(client, "verifyManifest", new Class<?>[]{String.class}, fixture(BuildConfig.EDITION));
        assertEquals(BuildConfig.EDITION, valid.getString("edition"));
        assertEquals("org.cyphra.browser." + BuildConfig.EDITION, valid.getString("packageName"));
        assertEquals("android-v0.1.0", valid.getString("tag"));
        String otherEdition = "team".equals(BuildConfig.EDITION) ? "public" : "team";
        rejects(() -> invoke(client, "verifyManifest", new Class<?>[]{String.class}, fixture(otherEdition)));
        JSONObject envelope = new JSONObject(fixture(BuildConfig.EDITION));
        String signature = envelope.getString("signature");
        envelope.put("signature", (signature.charAt(0) == 'A' ? "B" : "A") + signature.substring(1));
        rejects(() -> invoke(client, "verifyManifest", new Class<?>[]{String.class}, envelope.toString()));
        JSONObject extra = new JSONObject(fixture(BuildConfig.EDITION)); extra.put("untrusted", true);
        rejects(() -> invoke(client, "verifyManifest", new Class<?>[]{String.class}, extra.toString()));
        rejects(() -> invoke(client, "verifyManifest", new Class<?>[]{String.class}, "{}"));
    }

    public void testOnlyRepositoryApiAndGitHubAssetCdnAllowed() throws Exception {
        UpdateClient client = updater("personal");
        String api = "https://api.github.com/repos/" + BuildConfig.REPOSITORY;
        assertEquals(true, invoke(client, "isApiRequest", new Class<?>[]{String.class}, api + "/releases?per_page=30&page=1"));
        assertEquals(true, invoke(client, "isApiRequest", new Class<?>[]{String.class}, api + "/releases/assets/123"));
        for (String invalid : new String[]{"http://api.github.com/repos/" + BuildConfig.REPOSITORY + "/releases/assets/123",
            "https://api.github.com/repos/attacker/browser/releases/assets/123", api + "/releases/latest",
            api + "/releases/assets/123?token=secret", api + "/releases?per_page=30&page=6", "https://api.github.com@evil.example/a"}) {
            assertEquals(false, invoke(client, "isApiRequest", new Class<?>[]{String.class}, invalid));
        }
        String allowed = "https://release-assets.githubusercontent.com/github-production-release-asset/123/abc?sig=fixture";
        assertEquals(true, invoke(client, "isAssetRedirect", new Class<?>[]{String.class}, allowed));
        for (String invalid : new String[]{allowed.replace("https:", "http:"), allowed.replace(".com/", ".com.evil.example/"),
            allowed.replace("https://", "https://secret@"), allowed + "#fragment", "https://raw.githubusercontent.com/owner/repo/file",
            "https://release-assets.githubusercontent.com:443/github-production-release-asset/123/abc"}) {
            assertEquals(false, invoke(client, "isAssetRedirect", new Class<?>[]{String.class}, invalid));
        }
    }

    public void testCredentialsAreEncryptedAndBoundToMode() throws Exception {
        UpdateClient work = updater("work"), personal = updater("personal");
        String fake = "github_pat_fixturefixturefixturefixturefixturefixturefixturefixture";
        rejects(() -> work.configureToken("ghp_classic_token_is_not_a_fine_grained_read_token"));
        work.configureToken(fake);
        BrowserStore workStore = new BrowserStore(target, "work", BuildConfig.EDITION);
        String encrypted = workStore.stringPref("github-token-encrypted", "");
        assertTrue(work.hasToken()); assertFalse(personal.hasToken()); assertFalse(encrypted.contains(fake));
        assertEquals(fake, invoke(work, "credential", new Class<?>[]{}));
        BrowserStore personalStore = new BrowserStore(target, "personal", BuildConfig.EDITION);
        personalStore.setStringPref("github-token-encrypted", encrypted);
        rejects(() -> invoke(personal, "credential", new Class<?>[]{}));
        work.forgetToken(); assertFalse(work.hasToken());
    }

    public void testSavedApkMustPassEveryInstallCheck() throws Exception {
        // A fixed older test baseline lets the signed, deliberately non-APK
        // fixture reach each install boundary after newer Cyphra releases.
        // verifyPackage still reads the real installed package and certificate.
        UpdateClient.Config baseline=new UpdateClient.Config(BuildConfig.EDITION,BuildConfig.REPOSITORY,BuildConfig.UPDATE_KEY_ID,
            BuildConfig.UPDATE_KEY_SPKI,BuildConfig.ASSET_PREFIX,"0.0.0",1,target.getPackageName());
        UpdateClient client = new UpdateClient(target,new BrowserStore(target,"work",BuildConfig.EDITION),baseline);
        UpdateClient personal = new UpdateClient(target,new BrowserStore(target,"personal",BuildConfig.EDITION),baseline);
        String envelope = fixtureFile("updater-invalid-apk-" + BuildConfig.EDITION + ".json");
        JSONObject manifest = (JSONObject) invoke(client, "verifyManifest", new Class<?>[]{String.class}, envelope);
        Constructor<UpdateClient.Offer> constructor = UpdateClient.Offer.class.getDeclaredConstructor(JSONObject.class, String.class, String.class, boolean.class);
        constructor.setAccessible(true);
        UpdateClient.Offer offer = constructor.newInstance(manifest, envelope,
            "https://api.github.com/repos/" + BuildConfig.REPOSITORY + "/releases/assets/123", true);
        File folder = new File(target.getCacheDir(), "updates-work");
        if (!folder.isDirectory() && !folder.mkdirs()) throw new IllegalStateException("Test cache could not be created.");
        File file = new File(folder, offer.name);
        File other = new File(target.getCacheDir(), "outside-" + offer.name);
        String changed="The saved APK changed after verification. Download it again.";
        try {
            try (FileOutputStream output = new FileOutputStream(file)) { output.write('x'); }
            // Matching signed hash and size still cannot turn a non-APK into an
            // Android package, nor bypass installed package/signer policy.
            rejectsWithMessage("The APK package or version does not match this installation.",() -> client.verifyForInstall(file, offer));
            try (FileOutputStream output = new FileOutputStream(file)) { output.write('y'); }
            rejectsWithMessage(changed,() -> client.verifyForInstall(file, offer));
            try (FileOutputStream output = new FileOutputStream(file)) { output.write(new byte[]{'x','x'}); }
            rejectsWithMessage(changed,() -> client.verifyForInstall(file, offer));
            // Boundary cases use the original correct size/hash, so an invalid
            // payload cannot hide a missing cache path or mode boundary check.
            try (FileOutputStream output = new FileOutputStream(file)) { output.write('x'); }
            try (FileOutputStream output = new FileOutputStream(other)) { output.write('x'); }
            rejectsWithMessage(changed,() -> client.verifyForInstall(other, offer));
            rejectsWithMessage(changed,() -> personal.verifyForInstall(file, offer));
        } finally { file.delete(); other.delete(); }
    }

    public void testModernTlsProtocolsAndCiphers() throws Exception {
        try (javax.net.ssl.SSLSocket socket = (javax.net.ssl.SSLSocket) UpdateClient.secureSocketFactory().createSocket()) {
            assertTrue(socket.getEnabledProtocols().length > 0);
            for (String protocol : socket.getEnabledProtocols()) assertTrue(protocol.equals("TLSv1.2") || protocol.equals("TLSv1.3"));
            assertTrue(socket.getEnabledCipherSuites().length > 0);
            for (String suite : socket.getEnabledCipherSuites()) {
                assertTrue(suite.startsWith("TLS_")); assertFalse(suite.startsWith("TLS_RSA_WITH_"));
                assertTrue(suite.contains("_GCM_") || suite.contains("_CHACHA20_"));
                assertTrue(suite.startsWith("TLS_AES_") || suite.startsWith("TLS_CHACHA20_")
                    || suite.startsWith("TLS_ECDHE_") || suite.startsWith("TLS_DHE_"));
            }
        }
    }

    /** Optional full release download from an older signed disposable install. */
    private JSONObject testRealPublishedGitHubUpdate() throws Exception {
        UpdateClient client = updater("personal");
        if (client.requiresToken()) throw new IllegalStateException("The native private update network check requires a user-configured fine-grained token.");
        UpdateClient.Offer offer = client.check();
        if (!offer.newer) throw new IllegalStateException("Install the older signed fixture before the native update qualification.");
        File apk = client.download(offer);
        try {
            client.verifyForInstall(apk, offer);
            long offset = apk.length() - 1;
            int original;
            try (RandomAccessFile file = new RandomAccessFile(apk, "rw")) {
                file.seek(offset); original = file.readUnsignedByte();
                file.seek(offset); file.write(original ^ 1); file.getFD().sync();
            }
            try { rejects(() -> client.verifyForInstall(apk, offer)); }
            finally {
                try (RandomAccessFile file = new RandomAccessFile(apk, "rw")) {
                    file.seek(offset); file.write(original); file.getFD().sync();
                }
            }
            client.verifyForInstall(apk, offer);
            JSONObject result = new JSONObject();
            result.put("passed", true); result.put("repository", BuildConfig.REPOSITORY);
            result.put("version", offer.version); result.put("packageName", offer.packageName);
            result.put("size", offer.size); result.put("sha256", offer.sha256);
            result.put("anonymous", true); result.put("fullDownload", true);
            result.put("manifestSignatureVerified", true); result.put("apkSignerMatchesInstalled", true);
            result.put("tamperRefused", true); result.put("installerInvoked", false);
            return result;
        } finally { apk.delete(); }
    }
}
