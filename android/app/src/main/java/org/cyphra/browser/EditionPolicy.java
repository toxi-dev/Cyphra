/* MPL-2.0. Pure edition boundaries shared by routing, storage, sync and updates. */
package org.cyphra.browser;

final class EditionPolicy {
    private EditionPolicy() {}
    static boolean validEdition(String edition) {
        return "team".equals(edition)||"public".equals(edition)||"home".equals(edition);
    }
    static boolean allowsMode(String edition,String mode) {
        return validEdition(edition)&&("personal".equals(mode)||(!"home".equals(edition)&&"work".equals(mode)));
    }
    static String launchMode(String edition,String requested,String saved,String fallback) {
        if(!validEdition(edition))throw new IllegalArgumentException("Invalid browser edition.");
        if("home".equals(edition))return "personal";
        if(allowsMode(edition,requested))return requested;
        if(allowsMode(edition,saved))return saved;
        if(!allowsMode(edition,fallback))throw new IllegalArgumentException("Invalid default profile.");
        return fallback;
    }
    // Only this installed flavor supplies trusted updater identity. Keeping
    // foreign repositories and release key identifiers out of shared runtime
    // code also keeps private edition metadata out of public/Home DEX files.
    private static void requireInstalledEdition(String edition) {
        if(!BuildConfig.EDITION.equals(edition))throw new IllegalArgumentException("Update configuration belongs to another edition.");
    }
    static String repository(String edition) {
        requireInstalledEdition(edition);return BuildConfig.REPOSITORY;
    }
    static String assetPrefix(String edition) {
        requireInstalledEdition(edition);return BuildConfig.ASSET_PREFIX;
    }
    static String keyId(String edition) {
        requireInstalledEdition(edition);return BuildConfig.UPDATE_KEY_ID;
    }
}
