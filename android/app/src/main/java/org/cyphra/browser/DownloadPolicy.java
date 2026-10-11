/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Treat server-provided download metadata as a filename, never a filesystem path. */
final class DownloadPolicy {
    private static final Pattern PARAMETER = Pattern.compile(
        "(?i)(?:^|;)\\s*(filename\\*|filename)\\s*=\\s*(\"(?:[^\"\\\\]|\\\\.)*\"|[^;]*)");
    private static final Pattern MIME = Pattern.compile("[a-z0-9!#$&^_.+\\-]+/[a-z0-9!#$&^_.+\\-]+");
    private static final int MAX_NAME = 120;

    static final class Metadata {
        final String filename, mimeType;
        Metadata(String filename, String mimeType) { this.filename = filename; this.mimeType = mimeType; }
    }

    static Metadata derive(String url, String disposition, String contentType) {
        String mime = mimeType(contentType);
        String name = dispositionName(disposition);
        if (name == null) {
            try {
                String path = new URI(url).getPath();
                if (path != null) name = path.substring(path.lastIndexOf('/') + 1);
            } catch (Exception ignored) { /* A malformed URL cannot choose a local path. */ }
        }
        name = safeName(name);
        // Retain an explicit filename extension. When the server omitted one,
        // a small known MIME mapping keeps common documents usable in Android.
        String extension = extension(mime);
        if (name.lastIndexOf('.') <= 0 && !extension.isEmpty()) name += extension;
        return new Metadata(limit(name), mime);
    }

    private static String dispositionName(String value) {
        if (value == null || value.length() > 8192 || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0) return null;
        Matcher matcher = PARAMETER.matcher(value);
        String ordinary = null, encoded = null;
        while (matcher.find()) {
            String name = matcher.group(1).toLowerCase(Locale.ROOT), candidate = matcher.group(2).trim();
            if (candidate.startsWith("\"") && candidate.endsWith("\""))
                candidate = candidate.substring(1, candidate.length() - 1).replaceAll("\\\\(.)", "$1");
            if ("filename*".equals(name) && encoded == null) {
                try {
                    int first = candidate.indexOf('\''), second = candidate.indexOf('\'', first + 1);
                    if (first < 0 || second < 0 || !"UTF-8".equalsIgnoreCase(candidate.substring(0, first))) continue;
                    encoded = decodeUtf8(candidate.substring(second + 1));
                    if (encoded.isEmpty()) encoded = null;
                } catch (Exception ignored) { /* Invalid extended metadata falls back to filename or URL. */ }
            } else if ("filename".equals(name) && ordinary == null && !candidate.isEmpty()) ordinary = candidate;
        }
        return encoded != null ? encoded : ordinary;
    }

    private static String decodeUtf8(String value) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            if (ch == '%') {
                if (i + 2 >= value.length()) throw new IllegalArgumentException();
                int high = Character.digit(value.charAt(++i), 16), low = Character.digit(value.charAt(++i), 16);
                if (high < 0 || low < 0) throw new IllegalArgumentException();
                bytes.write(high * 16 + low);
            } else {
                if (ch < 0x21 || ch > 0x7e || ch == '\'' || ch == '"' || ch == '\\') throw new IllegalArgumentException();
                bytes.write(ch); // '+' is a literal filename character, never a form-encoded space.
            }
        }
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
    }

    private static String safeName(String value) {
        if (value == null) return "download";
        String leaf = value.substring(Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\')) + 1);
        StringBuilder safe = new StringBuilder();
        leaf.codePoints().forEach(ch -> {
            if (Character.isLetterOrDigit(ch) || ch == ' ' || ch == '.' || ch == '_' || ch == '-'
                || ch == '(' || ch == ')' || ch == '+' || Character.getType(ch) == Character.NON_SPACING_MARK)
                safe.appendCodePoint(ch);
            else safe.append('_');
        });
        String result = safe.toString().trim().replaceFirst("^[. ]+", "").replaceFirst("[. ]+$", "");
        return result.isEmpty() ? "download" : limit(result);
    }

    private static String limit(String value) {
        if (value.codePointCount(0, value.length()) <= MAX_NAME && value.getBytes(StandardCharsets.UTF_8).length <= 240) return value;
        int dot = value.lastIndexOf('.');
        String suffix = dot > 0 && value.length() - dot <= 16 ? value.substring(dot) : "";
        String stem = suffix.isEmpty() ? value : value.substring(0, dot);
        int count = Math.min(stem.codePointCount(0, stem.length()), MAX_NAME - suffix.codePointCount(0, suffix.length()));
        String result = stem.substring(0, stem.offsetByCodePoints(0, count)).trim() + suffix;
        while (result.getBytes(StandardCharsets.UTF_8).length > 240 && count > 0)
            result = stem.substring(0, stem.offsetByCodePoints(0, --count)).trim() + suffix;
        return result;
    }

    private static String mimeType(String value) {
        if (value == null || value.length() > 512 || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0) return "application/octet-stream";
        String type = value.split(";", 2)[0].trim().toLowerCase(Locale.ROOT);
        return MIME.matcher(type).matches() ? type : "application/octet-stream";
    }

    private static String extension(String mime) {
        return switch (mime) {
            case "application/pdf" -> ".pdf";
            case "application/zip" -> ".zip";
            case "application/json" -> ".json";
            case "application/vnd.android.package-archive" -> ".apk";
            case "text/plain" -> ".txt";
            case "text/csv" -> ".csv";
            case "text/html" -> ".html";
            case "image/jpeg" -> ".jpg";
            case "image/png" -> ".png";
            case "image/gif" -> ".gif";
            case "image/webp" -> ".webp";
            case "image/svg+xml" -> ".svg";
            case "audio/mpeg" -> ".mp3";
            case "video/mp4" -> ".mp4";
            case "video/webm" -> ".webm";
            default -> "";
        };
    }
}
