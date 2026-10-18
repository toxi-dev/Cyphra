/* MPL-2.0. Edition boundaries must fail before storage, networking or runtime creation. */
package org.cyphra.browser;
import org.junit.Test;
import static org.junit.Assert.*;

public final class EditionPolicyTest {
    @Test public void homeNeverCreatesWorkFromSavedOrExternalMode(){
        for(String request:new String[]{null,"work","personal","other"})for(String saved:new String[]{null,"work","personal","other"})
            assertEquals("personal",EditionPolicy.launchMode("home",request,saved,"work"));
        assertFalse(EditionPolicy.allowsMode("home","work"));assertTrue(EditionPolicy.allowsMode("home","personal"));
    }
    @Test public void existingEditionsKeepTheirExplicitAndSavedModes(){
        for(String edition:new String[]{"team","public"}){
            assertEquals("work",EditionPolicy.launchMode(edition,"work","personal","personal"));
            assertEquals("personal",EditionPolicy.launchMode(edition,"personal","work","work"));
            assertEquals("work",EditionPolicy.launchMode(edition,"invalid","work","personal"));
            assertEquals("personal",EditionPolicy.launchMode(edition,null,"invalid","personal"));
        }
    }
    @Test public void installedUpdateIdentityRefusesForeignEditions(){
        assertEquals(BuildConfig.REPOSITORY,EditionPolicy.repository(BuildConfig.EDITION));
        assertEquals(BuildConfig.ASSET_PREFIX,EditionPolicy.assetPrefix(BuildConfig.EDITION));
        assertEquals(BuildConfig.UPDATE_KEY_ID,EditionPolicy.keyId(BuildConfig.EDITION));
        for(String edition:new String[]{"team","public","home"})if(!edition.equals(BuildConfig.EDITION)){
            try{EditionPolicy.repository(edition);fail("Foreign update repository accepted.");}catch(IllegalArgumentException expected){}
            try{EditionPolicy.assetPrefix(edition);fail("Foreign update asset prefix accepted.");}catch(IllegalArgumentException expected){}
            try{EditionPolicy.keyId(edition);fail("Foreign update key accepted.");}catch(IllegalArgumentException expected){}
        }
    }
    @Test public void unknownEditionsAndProfilesAreNotAccepted(){
        for(String edition:new String[]{null,"byte-home","Home","other"}){
            assertFalse(EditionPolicy.validEdition(edition));assertFalse(EditionPolicy.allowsMode(edition,"personal"));
            try{EditionPolicy.launchMode(edition,"personal",null,"personal");fail("Unknown edition accepted.");}catch(IllegalArgumentException expected){}
        }
        assertFalse(EditionPolicy.allowsMode("home",null));assertFalse(EditionPolicy.allowsMode("team","private"));
    }
}
