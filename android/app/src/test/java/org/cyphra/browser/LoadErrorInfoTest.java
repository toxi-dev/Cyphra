/* MPL-2.0. A connection, certificate, or proxy error must not blame DNS. */
package org.cyphra.browser;
import org.junit.Test;
import org.mozilla.geckoview.WebRequestError;
import static org.junit.Assert.*;
public final class LoadErrorInfoTest {
    @Test public void onlyActualNameLookupFailureOffersDnsTroubleshooting(){
        assertTrue(LoadErrorInfo.from(WebRequestError.ERROR_UNKNOWN_HOST,WebRequestError.ERROR_CATEGORY_URI,true).dnsRelated);
        for(int code:new int[]{WebRequestError.ERROR_CONNECTION_REFUSED,WebRequestError.ERROR_NET_TIMEOUT,WebRequestError.ERROR_NET_RESET,WebRequestError.ERROR_OFFLINE}){
            LoadErrorInfo info=LoadErrorInfo.from(code,WebRequestError.ERROR_CATEGORY_NETWORK,true);
            assertFalse(info.dnsRelated);assertFalse(info.message.contains("DNS"));
        }
    }
    @Test public void secureAndProxyFailuresRemainDistinctFromResolverChoice(){
        for(int category:new int[]{WebRequestError.ERROR_CATEGORY_SECURITY,WebRequestError.ERROR_CATEGORY_PROXY}){
            LoadErrorInfo info=LoadErrorInfo.from(WebRequestError.ERROR_UNKNOWN,category,true);
            assertFalse(info.dnsRelated);assertFalse(info.message.contains("DNS"));
        }
    }
    @Test public void selectedDnsIsNotAutomaticallyCalledBroken(){
        LoadErrorInfo info=LoadErrorInfo.from(WebRequestError.ERROR_UNKNOWN_HOST,WebRequestError.ERROR_CATEGORY_URI,true);
        assertTrue(info.message.contains("did not return an address"));assertFalse(info.message.contains("unavailable"));
        assertFalse(LoadErrorInfo.from(WebRequestError.ERROR_UNKNOWN_HOST,WebRequestError.ERROR_CATEGORY_URI,false).message.contains("selected DNS"));
    }
    @Test public void unknownErrorsDoNotInventACause(){
        LoadErrorInfo info=LoadErrorInfo.from(-1,WebRequestError.ERROR_CATEGORY_UNKNOWN,true);
        assertFalse(info.dnsRelated);assertFalse(info.message.contains("DNS"));assertFalse(info.message.contains("unsafe"));
    }
}
