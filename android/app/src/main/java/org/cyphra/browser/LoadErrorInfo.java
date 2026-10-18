/* MPL-2.0. Explain the measured Gecko error without guessing a DNS failure. */
package org.cyphra.browser;

import org.mozilla.geckoview.WebRequestError;

final class LoadErrorInfo {
    final String title, message;
    final boolean dnsRelated;
    private LoadErrorInfo(String title,String message,boolean dnsRelated){this.title=title;this.message=message;this.dnsRelated=dnsRelated;}
    static LoadErrorInfo from(int code,int category,boolean encryptedDNS){
        if(code==WebRequestError.ERROR_UNKNOWN_HOST)return new LoadErrorInfo("This site could not be found",
            encryptedDNS?"Your selected DNS provider did not return an address for this site. Check the address or your DNS settings.":"An address could not be found for this site. Check the spelling and your connection.",true);
        if(category==WebRequestError.ERROR_CATEGORY_SECURITY)return new LoadErrorInfo("Secure connection failed","Cyphra could not verify this site's secure connection. Check the address or try again later.",false);
        if(category==WebRequestError.ERROR_CATEGORY_SAFEBROWSING)return new LoadErrorInfo("This site was blocked","The browser identified this address as unsafe.",false);
        if(category==WebRequestError.ERROR_CATEGORY_PROXY)return new LoadErrorInfo("Proxy connection failed","The configured proxy could not connect. Check the proxy settings or try again later.",false);
        switch(code){
            case WebRequestError.ERROR_CONNECTION_REFUSED:return new LoadErrorInfo("This site could not be reached","The server refused the connection. It may be unavailable or the address may be incorrect.",false);
            case WebRequestError.ERROR_NET_TIMEOUT:return new LoadErrorInfo("This site took too long to respond","The connection timed out. Try again or check your connection.",false);
            case WebRequestError.ERROR_OFFLINE:return new LoadErrorInfo("You are offline","Check your device's connection, then try again.",false);
            case WebRequestError.ERROR_NET_RESET:
            case WebRequestError.ERROR_NET_INTERRUPT:return new LoadErrorInfo("The connection was interrupted","The connection ended before the page finished loading. Try again.",false);
            case WebRequestError.ERROR_MALFORMED_URI:
            case WebRequestError.ERROR_UNKNOWN_PROTOCOL:return new LoadErrorInfo("Check this address","Cyphra could not open this address. Use a complete website address beginning with https:// or http://.",false);
            case WebRequestError.ERROR_LOCAL_NETWORK_ACCESS_DENIED:return new LoadErrorInfo("Local network access was denied","This page could not access the requested local network address.",false);
            default:return new LoadErrorInfo("This page could not load","The browser could not finish this request. Check the address or try again.",false);
        }
    }
}
