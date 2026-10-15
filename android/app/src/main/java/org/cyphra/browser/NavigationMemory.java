/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

/** Keeps an attachment's request URI separate from the document that remains on screen. */
final class NavigationMemory {
    String documentUrl="about:blank",documentTitle="New tab";
    long serial;
    private String previousUrl="about:blank",previousTitle="New tab",requestedUri,attachmentUri;
    private long attachmentSerial=-1;
    private boolean prepared;

    void prepare(String uri){begin();requestedUri=uri;prepared=true;}
    void request(String uri,boolean redirect){
        // App navigation records the old document before opening/loading Gecko.
        // Its subsequent native callback must not recapture an early location.
        if(!redirect&&(!prepared||!sameResource(uri,requestedUri)))begin();
        requestedUri=uri;prepared=false;
    }
    private void begin(){previousUrl=documentUrl;previousTitle=documentTitle;serial++;attachmentUri=null;}
    boolean retainingDocument(){return attachmentSerial==serial;}
    boolean acceptsPageStart(String uri){
        // Gecko can deliver the attachment's progress start after its external
        // response. That late callback must not clear the restored protection
        // context/counters. A new request advances serial, including the same URI.
        return !retainingDocument()||!sameResource(uri,attachmentUri);
    }
    boolean location(String uri){
        // Some callback orders deliver the attachment location after the external
        // response. It must not become a restored tab or overwrite the old page.
        if(!acceptsPageStart(uri))return false;
        documentUrl=uri;return true;
    }
    void title(String title){documentTitle=title;}
    boolean external(String uri){
        // A response from an older navigation cannot replace a newer destination.
        if(requestedUri!=null&&!sameResource(uri,requestedUri))return false;
        documentUrl=previousUrl;documentTitle=previousTitle;attachmentUri=uri;attachmentSerial=serial;requestedUri=null;prepared=false;return true;
    }
    void home(){documentUrl="about:blank";documentTitle="New tab";previousUrl=documentUrl;previousTitle=documentTitle;requestedUri=null;attachmentUri=null;attachmentSerial=-1;prepared=false;serial++;}
    private static boolean sameResource(String first,String second){if(first==null||second==null)return false;int a=first.indexOf('#'),b=second.indexOf('#');return (a<0?first:first.substring(0,a)).equals(b<0?second:second.substring(0,b));}
}
