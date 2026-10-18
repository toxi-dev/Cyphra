/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
package org.cyphra.browser;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.net.IDN;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Local, mode-bound browser data. Neither mode reads the other mode's file. */
public final class BrowserStore {
    private static final int MAX_ITEMS = 2000;
    private static final int MAX_DATA_CHARS = 4 * 1024 * 1024;
    private final SharedPreferences preferences;
    private final String mode;
    private final String edition;

    public BrowserStore(Context context, String mode, String edition) {
        if (!EditionPolicy.allowsMode(edition,mode)) throw new IllegalArgumentException("Invalid edition or browser mode.");
        this.mode = mode;
        this.edition = edition;
        preferences = context.getApplicationContext().getSharedPreferences("cyphra-data-" + mode, Context.MODE_PRIVATE);
    }

    public String mode() { return mode; }
    public String edition() { return edition; }
    public boolean booleanPref(String key, boolean fallback) { return preferences.getBoolean(key, fallback); }
    public void setBooleanPref(String key, boolean value) { commit(preferences.edit().putBoolean(key, value)); }
    public String stringPref(String key, String fallback) { return preferences.getString(key, fallback); }
    public void setStringPref(String key, String value) { commit(preferences.edit().putString(key, value)); }
    public void removePref(String key) { commit(preferences.edit().remove(key)); }
    public void removePrefs(String... keys) { SharedPreferences.Editor edit=preferences.edit();for(String key:keys)edit.remove(key);commit(edit); }

    public JSONArray bookmarks() { return read("bookmarks"); }
    public JSONArray history() { return read("history"); }
    public JSONArray tabs() { return read("tabs"); }
    public int selectedTab() { return preferences.getInt("tabs-selected", 0); }

    public synchronized void addBookmark(String title, String url) {
        requireWebURL(url);
        JSONArray result = new JSONArray();
        result.put(entry(title, url));
        JSONArray previous = bookmarks();
        for (int i = 0; i < previous.length() && result.length() < MAX_ITEMS; i++) {
            JSONObject item = previous.optJSONObject(i);
            if (item != null && !url.equals(item.optString("url"))) result.put(item);
        }
        write("bookmarks", result);
    }

    public synchronized void removeBookmark(String url) {
        JSONArray previous = bookmarks(), result = new JSONArray();
        for (int i = 0; i < previous.length(); i++) {
            JSONObject item = previous.optJSONObject(i);
            if (item != null && !url.equals(item.optString("url"))) result.put(item);
        }
        write("bookmarks", result);
    }

    public boolean hasBookmark(String url) {
        JSONArray items = bookmarks();
        for (int i = 0; i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);
            if (item != null && url.equals(item.optString("url"))) return true;
        }
        return false;
    }

    /** Work mode records no browsing history unless the user explicitly enables it. */
    public synchronized void recordVisit(String title, String url) {
        if (!booleanPref("save-history", "personal".equals(mode)) || !isWebURL(url)) return;
        JSONArray previous = history(), result = new JSONArray();
        result.put(entry(title, url));
        for (int i = 0; i < previous.length() && result.length() < MAX_ITEMS; i++) {
            JSONObject item = previous.optJSONObject(i);
            if (item != null && !url.equals(item.optString("url"))) result.put(item);
        }
        write("history", result);
    }

    public void clearHistory() { commit(preferences.edit().remove("history")); }

    /** Session URLs only; cookies and logins belong to the isolated Gecko profile. */
    public void saveTabs(JSONArray input) {
        saveTabs(input, selectedTab());
    }

    /** Save the ordinary tab list and its selected index in the same transaction. */
    public synchronized void saveTabs(JSONArray input, int selectedIndex) {
        JSONArray result = new JSONArray();
        int selected = 0;
        for (int i = 0; i < input.length() && result.length() < 100; i++) {
            Object value = input.opt(i);
            Object accepted = null;
            if (value instanceof String && ("about:blank".equals(value) || isWebURL((String) value))) accepted = value;
            else if (value instanceof JSONObject) {
                JSONObject item = (JSONObject) value;
                String url = item.optString("url");
                if (!item.optBoolean("private", false) && ("about:blank".equals(url) || isWebURL(url))) accepted = entry(item.optString("title"), url);
            }
            if (accepted != null) {
                if (i <= selectedIndex) selected = result.length();
                result.put(accepted);
            }
        }
        JSONArray bounded = bounded(result);
        selected = Math.min(selected, Math.max(0, bounded.length() - 1));
        commit(preferences.edit().putString("tabs", bounded.toString()).putInt("tabs-selected", selected));
    }

    private JSONArray read(String key) {
        String serialized = preferences.getString(key, "[]");
        if (serialized == null || serialized.length() > MAX_DATA_CHARS) return new JSONArray();
        try {
            JSONArray value = new JSONArray(serialized);
            return value.length() <= MAX_ITEMS ? value : new JSONArray();
        } catch (JSONException error) { return new JSONArray(); }
    }

    private void write(String key, JSONArray value) {
        commit(preferences.edit().putString(key, bounded(value).toString()));
    }
    private static JSONArray bounded(JSONArray value) {
        // Keep the newest entries when unusually long URLs reach the data cap;
        // never write a collection that the bounded reader would later discard.
        JSONArray bounded = new JSONArray(); int length = 2;
        for (int i = 0; i < value.length(); i++) {
            Object item = value.opt(i);
            if (item == null) continue;
            int added = new JSONArray().put(item).toString().length() - 2 + (bounded.length() == 0 ? 0 : 1);
            if (length + added > MAX_DATA_CHARS) break;
            bounded.put(item); length += added;
        }
        return bounded;
    }
    private static void commit(SharedPreferences.Editor edit) {
        if (!edit.commit()) throw new IllegalStateException("Cyphra could not save this profile. Check the device's available storage.");
    }
    private static JSONObject entry(String title, String url) {
        JSONObject value = new JSONObject();
        try {
            value.put("title", title == null ? "" : title.substring(0, Math.min(512, title.length())));
            value.put("url", url);
            value.put("visited", System.currentTimeMillis());
        } catch (JSONException impossible) { throw new IllegalStateException(impossible); }
        return value;
    }

    public static boolean isWebURL(String input) {
        try {
            if (input == null || input.length() > 16384 || input.matches("(?s).*[\\x00-\\x20\\x7f].*")) return false;
            URI uri = new URI(input);
            String scheme = uri.getScheme();
            return ("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme))
                && uri.getHost() != null && !uri.getHost().isEmpty() && uri.getRawUserInfo() == null
                && (uri.getPort() == -1 || uri.getPort() > 0 && uri.getPort() <= 65535);
        } catch (Exception error) { return false; }
    }
    private static void requireWebURL(String input) {
        if (!isWebURL(input)) throw new IllegalArgumentException("Only website addresses can be saved.");
    }

    /** An address bar is never a script, local-file or Android intent launcher. */
    public static String navigation(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty() || value.length() > 16384 || value.matches("(?s).*[\\x00-\\x1f\\x7f].*"))
            throw new IllegalArgumentException("Enter a website address or search query.");
        if (value.matches("(?i)^(javascript|data|file|content|intent|android-app|blob|chrome|resource|about|view-source):.*"))
            throw new IllegalArgumentException("This address type cannot be opened from the address bar.");
        if (value.matches("(?i)^https?://.*")) {
            String canonical = asciiHost(value);
            requireWebURL(canonical);
            return canonical;
        }
        // A bare domain, bracketed IPv6 address, IPv4 address or localhost with
        // an optional port/path is an HTTPS address. Everything else is a query.
        if (!value.contains(" ") && value.matches("(?i)^(localhost|\\[[0-9a-f:]+\\]|[^/@:]+\\.[^/@:]+)(:[0-9]{1,5})?([/?#].*)?$")) {
            String canonical = asciiHost("https://" + value);
            requireWebURL(canonical);
            return canonical;
        }
        try { return "https://search.brave.com/search?q=" + URLEncoder.encode(value, StandardCharsets.UTF_8.name()); }
        catch (java.io.UnsupportedEncodingException impossible) { throw new IllegalStateException(impossible); }
    }

    private static String asciiHost(String value) {
        try {
            URI uri = new URI(value);
            String authority = uri.getRawAuthority();
            if (authority == null || authority.contains("@") || authority.contains("\\")) throw new IllegalArgumentException("Invalid website address.");
            if (uri.getHost() != null) return uri.toASCIIString();
            int colon = authority.lastIndexOf(':');
            String host = colon >= 0 ? authority.substring(0, colon) : authority;
            String port = colon >= 0 ? authority.substring(colon) : "";
            String ascii = IDN.toASCII(host, IDN.USE_STD3_ASCII_RULES).toLowerCase(Locale.ROOT);
            URI result = new URI(uri.getScheme().toLowerCase(Locale.ROOT) + "://" + ascii + port
                + (uri.getRawPath() == null ? "" : uri.getRawPath())
                + (uri.getRawQuery() == null ? "" : "?" + uri.getRawQuery())
                + (uri.getRawFragment() == null ? "" : "#" + uri.getRawFragment()));
            return result.toASCIIString();
        } catch (Exception error) { throw new IllegalArgumentException("Invalid website address."); }
    }
}
