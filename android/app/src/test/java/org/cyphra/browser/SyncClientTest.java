/* MPL-2.0. Synthetic public vectors: no real vault or pairing secret. */
package org.cyphra.browser;

import org.json.JSONObject;
import org.junit.Test;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import static org.junit.Assert.*;

public final class SyncClientTest {
    private static JSONObject fixture() throws Exception {
        try (InputStream in = SyncClientTest.class.getResourceAsStream("/sync-desktop-v2-fixture.json")) {
            if (in == null) throw new AssertionError("Missing desktop interoperability fixture.");
            return new JSONObject(new String(in.readAllBytes(), StandardCharsets.UTF_8));
        }
    }
    private interface Operation { void run() throws Exception; }
    private static void rejects(Operation operation) throws Exception {
        try { operation.run(); } catch (Exception expected) { return; }
        fail("Expected a rejected unsafe or unauthenticated sync operation.");
    }
    @Test public void desktopHKDFAndCiphertextInteroperate() throws Exception {
        JSONObject fixture = fixture(); String secret = fixture.getString("secret"), vault = fixture.getString("vault");
        SyncClient.Keys keys = SyncClient.keys(secret);
        assertEquals(fixture.getString("token"), keys.token);
        StringBuilder hex = new StringBuilder(); for (byte b : keys.encryption.getEncoded()) hex.append(String.format("%02x", b & 255));
        assertEquals(fixture.getString("encryption"), hex.toString());
        JSONObject decoded = SyncClient.decryptPayload(fixture.getJSONObject("envelope"), secret, vault);
        assertEquals("https://example.org/security", decoded.getJSONObject("records").getJSONObject("b:bookmark0001").getJSONObject("value").getString("url"));
        SyncClient.assertPayloadScope(decoded, fixture.getJSONObject("payload").getJSONObject("scope"));
        JSONObject encrypted = SyncClient.encryptPayload(decoded, secret, vault);
        assertFalse(encrypted.toString().contains("example.org"));
        assertNotEquals(encrypted.getString("nonce"), SyncClient.encryptPayload(decoded, secret, vault).getString("nonce"));
        assertEquals(decoded.getJSONObject("records").length(), SyncClient.decryptPayload(encrypted, secret, vault).getJSONObject("records").length());
    }
    @Test public void ciphertextSecretAndVaultIdentityAreAuthenticated() throws Exception {
        JSONObject fixture = fixture(); String secret = fixture.getString("secret"), vault = fixture.getString("vault");
        rejects(() -> SyncClient.decryptPayload(fixture.getJSONObject("envelope"), secret, "44444444444444444444444444444444"));
        rejects(() -> SyncClient.decryptPayload(fixture.getJSONObject("envelope"), "CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg", vault));
        JSONObject corrupt = new JSONObject(fixture.getJSONObject("envelope").toString());
        String value = corrupt.getString("ciphertext"); corrupt.put("ciphertext", (value.charAt(0) == 'A' ? "B" : "A") + value.substring(1));
        rejects(() -> SyncClient.decryptPayload(corrupt, secret, vault));
    }
    @Test public void editionAndModeBindingsCannotBeStrippedOrMixed() throws Exception {
        JSONObject payload = fixture().getJSONObject("payload");
        rejects(() -> SyncClient.assertPayloadScope(payload, new JSONObject("{\"edition\":\"public\",\"mode\":\"work\"}")));
        rejects(() -> SyncClient.assertPayloadScope(payload, new JSONObject("{\"edition\":\"team\",\"mode\":\"personal\"}")));
        JSONObject unscoped = new JSONObject(payload.toString()); unscoped.remove("scope");
        rejects(() -> SyncClient.assertPayloadScope(unscoped, payload.getJSONObject("scope")));
        JSONObject mismatch = new JSONObject(payload.toString()); mismatch.getJSONObject("scope").put("mode", "personal");
        rejects(() -> SyncClient.mergePayloads(payload, mismatch));
        String code = "cyphra-sync-v2.aHR0cHM6Ly9leGFtcGxlLm9yZw.11111111111111111111111111111111.BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc.team.work";
        assertEquals("https://example.org", SyncClient.parsePairingCode(code).getString("endpoint"));
        rejects(() -> SyncClient.parsePairingCode(code.replace("cyphra-sync-v2", "cyphra-sync-v1")));
    }
    @Test public void homePairingAndEncryptedPayloadsStayPersonalAndSeparate() throws Exception {
        JSONObject payload=new JSONObject(fixture().getJSONObject("payload").toString());
        JSONObject home=new JSONObject().put("edition","home").put("mode","personal");payload.put("scope",home);
        String code="cyphra-sync-v2.aHR0cHM6Ly9leGFtcGxlLm9yZw.11111111111111111111111111111111.BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc.home.personal";
        assertEquals("home",SyncClient.parsePairingCode(code).getJSONObject("scope").getString("edition"));
        rejects(()->SyncClient.parsePairingCode(code.replace("home.personal","home.work")));
        rejects(()->SyncClient.validateScope(new JSONObject().put("edition","home").put("mode","work")));
        JSONObject f=fixture();JSONObject encrypted=SyncClient.encryptPayload(payload,f.getString("secret"),f.getString("vault"));
        JSONObject decoded=SyncClient.decryptPayload(encrypted,f.getString("secret"),f.getString("vault"));SyncClient.assertPayloadScope(decoded,home);
        for(String edition:new String[]{"team","public"})rejects(()->SyncClient.assertPayloadScope(decoded,new JSONObject().put("edition",edition).put("mode","personal")));
        rejects(()->SyncClient.mergePayloads(payload,fixture().getJSONObject("payload")));
    }
    @Test public void onlySafeBookmarksAndSelectedPreferencesAreAccepted() throws Exception {
        JSONObject payload = fixture().getJSONObject("payload");
        JSONObject unsafe = new JSONObject(payload.toString());
        unsafe.getJSONObject("records").put("p:network.trr.uri", unsafe.getJSONObject("records").getJSONObject("p:places.history.enabled"));
        rejects(() -> SyncClient.validatePayload(unsafe));
        JSONObject cycle = new JSONObject(payload.toString());
        cycle.getJSONObject("records").getJSONObject("b:folder000001").getJSONObject("value").put("parentGuid", "folder000001");
        rejects(() -> SyncClient.validatePayload(cycle));
        JSONObject executable = new JSONObject(payload.toString());
        executable.getJSONObject("records").getJSONObject("b:bookmark0001").getJSONObject("value").put("url", "javascript:alert(1)");
        rejects(() -> SyncClient.validatePayload(executable));
        JSONObject stringClock = new JSONObject(payload.toString());
        stringClock.getJSONObject("records").getJSONObject("b:bookmark0001").put("clock", "1");
        rejects(() -> SyncClient.validatePayload(stringClock));
    }
    @Test public void tombstonesMergeWithoutDiscardingDesktopFoldersOrSettings() throws Exception {
        JSONObject payload = fixture().getJSONObject("payload"), tombstone = new JSONObject(payload.toString());
        tombstone.getJSONObject("records").put("b:bookmark0001", new JSONObject("{\"clock\":2,\"device\":\"33333333333333333333333333333333\",\"deleted\":true}"));
        JSONObject merged = SyncClient.mergePayloads(payload, tombstone);
        assertTrue(merged.getJSONObject("records").getJSONObject("b:bookmark0001").getBoolean("deleted"));
        assertTrue(merged.getJSONObject("records").has("b:folder000001"));
        assertTrue(merged.getJSONObject("records").has("s:https://example.org"));
        assertTrue(merged.getJSONObject("records").has("p:browser.uidensity"));
        JSONObject identity = new JSONObject(payload.toString());
        identity.getJSONObject("records").getJSONObject("b:bookmark0001").getJSONObject("value").put("title", "collision");
        rejects(() -> SyncClient.mergePayloads(payload, identity));
        JSONObject legacy = new JSONObject(payload.toString());
        legacy.getJSONObject("records").put("p:privacy.resistFingerprinting", new JSONObject("{\"clock\":3,\"device\":\"33333333333333333333333333333333\",\"deleted\":false,\"value\":true}"));
        assertFalse(SyncClient.mergePayloads(payload, legacy).getJSONObject("records").has("p:privacy.resistFingerprinting"));
    }
    @Test public void requestsRequireFinalHTTPSWithoutEmbeddedCredentials() throws Exception {
        assertEquals("https://example.org/cyphra-sync", SyncClient.endpointURL("https://EXAMPLE.org:443/cyphra-sync/"));
        for (String value : new String[] {"http://example.org", "https://user:pass@example.org/", "https://example.org/?secret=1", "https://example.org/../vault", "https://example.org/%2e%2e/"})
            rejects(() -> SyncClient.endpointURL(value));
    }
}
