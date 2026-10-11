/* MPL-2.0. Address-bar policy tests, independent of a running Android device. */
package org.cyphra.browser;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NavigationPolicyTest {
    @Test public void braveIsTheOnlySearchProvider() {
        assertEquals("https://search.brave.com/search?q=byte+team", BrowserStore.navigation("byte team"));
        assertEquals("https://search.brave.com/search?q=ftp%3A%2F%2Fexample.org", BrowserStore.navigation("ftp://example.org"));
        assertEquals("https://search.brave.com/search?q=cybersecurity", BrowserStore.navigation("cybersecurity"));
    }
    @Test public void normalizesWebsiteAddresses() {
        assertEquals("https://example.org", BrowserStore.navigation(" example.org "));
        assertEquals("https://example.org:8443/path?q=1#two", BrowserStore.navigation("example.org:8443/path?q=1#two"));
        assertEquals("http://localhost:9087/", BrowserStore.navigation("http://localhost:9087/"));
        assertEquals("https://localhost:9087/", BrowserStore.navigation("localhost:9087/"));
        assertEquals("https://[::1]:9087/", BrowserStore.navigation("[::1]:9087/"));
        assertEquals("https://127.0.0.1/", BrowserStore.navigation("127.0.0.1/"));
        assertEquals("https://xn--bcher-kva.example/", BrowserStore.navigation("https://bücher.example/"));
    }
    @Test public void rejectsActiveContentAndLocalFiles() {
        String[] values = {"javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,<script>",
            "file:///etc/passwd", "content://org.cyphra.browser.team.updates/a.apk", "intent://example/#Intent;end",
            "android-app://org.example", "blob:https://example.org/anything", "chrome://settings", "resource://gre/",
            "about:config", "view-source:https://example.org", "http://user:pass@example.org", "https://example.org:0",
            "https://example.org:65536", "https://example.org\\evil", "http://", "https://example.org/\nsecret", ""};
        for (String value : values) {
            try { BrowserStore.navigation(value); fail("Accepted unsafe address: " + value); }
            catch (IllegalArgumentException expected) {}
        }
    }
    @Test public void websiteValidationExcludesCredentialUrlsAndControls() {
        assertTrue(BrowserStore.isWebURL("https://example.org/a?b=c#d"));
        assertTrue(BrowserStore.isWebURL("http://127.0.0.1:8765/"));
        assertFalse(BrowserStore.isWebURL("https://user@example.org/"));
        assertFalse(BrowserStore.isWebURL("https://example.org/a b"));
        assertFalse(BrowserStore.isWebURL("javascript:alert(1)"));
        assertFalse(BrowserStore.isWebURL(null));
    }
    @Test public void comparesOnlyBoundedSemanticVersions() {
        assertTrue(UpdateClient.compareVersions("0.1.1", "0.1.0") > 0);
        assertTrue(UpdateClient.compareVersions("1.0.0", "0.99.99") > 0);
        assertTrue(UpdateClient.compareVersions("0.1.0", "0.1.1") < 0);
        assertEquals(0, UpdateClient.compareVersions("0.1.0", "0.1.0"));
        for (String value : new String[]{"01.1.0", "0.1", "0.1.0-beta", "-1.0.0", "10000.0.0", "v0.1.0"}) {
            try { UpdateClient.compareVersions(value, "0.1.0"); fail("Accepted invalid release version."); }
            catch (IllegalArgumentException expected) {}
        }
    }
}
