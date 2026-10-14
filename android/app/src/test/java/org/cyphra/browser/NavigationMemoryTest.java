/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import org.junit.Test;
import static org.junit.Assert.*;

public final class NavigationMemoryTest {
    private NavigationMemory document(){NavigationMemory state=new NavigationMemory();state.request("https://example.org/page",false);state.location("https://example.org/page");state.title("Working document");return state;}
    @Test public void earlyAttachmentLocationRestoresThePreviousDocument(){NavigationMemory state=document();state.request("https://example.org/file",false);state.location("https://example.org/file");state.title("Attachment");assertTrue(state.external("https://example.org/file"));assertEquals("https://example.org/page",state.documentUrl);assertEquals("Working document",state.documentTitle);}
    @Test public void appPreparationCannotRecaptureAnEarlyNativeLocation(){NavigationMemory state=document();state.prepare("https://example.org/file");state.location("https://example.org/file");state.request("https://example.org/file",false);assertTrue(state.external("https://example.org/file"));assertEquals("https://example.org/page",state.documentUrl);}
    @Test public void lateAttachmentLocationCannotOverwriteTheRestoredDocument(){NavigationMemory state=document();state.request("https://example.org/file",false);assertTrue(state.external("https://example.org/file"));assertFalse(state.location("https://example.org/file"));assertEquals("https://example.org/page",state.documentUrl);state.request("https://example.org/file",false);assertTrue(state.location("https://example.org/file"));}
    @Test public void redirectsKeepTheOriginalDocumentAndFragmentIsNotAnHttpResource(){NavigationMemory state=document();state.request("https://example.org/redirect",false);state.location("https://example.org/redirect");state.request("https://cdn.example.org/file#download",true);state.location("https://cdn.example.org/file#download");assertTrue(state.external("https://cdn.example.org/file"));assertEquals("https://example.org/page",state.documentUrl);}
    @Test public void oldExternalResponseCannotReplaceANewerNavigation(){NavigationMemory state=document();state.request("https://example.org/file",false);state.request("https://example.org/new-page",false);assertFalse(state.external("https://example.org/file"));assertEquals("https://example.org/page",state.documentUrl);assertTrue(state.location("https://example.org/new-page"));}
    @Test public void attachmentFromHomeStaysHomeAndALaterRequestInvalidatesCleanup(){NavigationMemory state=new NavigationMemory();state.request("https://example.org/file",false);state.location("https://example.org/file");assertTrue(state.external("https://example.org/file"));assertEquals("about:blank",state.documentUrl);long response=state.serial;state.request("https://example.org/page",false);assertNotEquals(response,state.serial);}
}
