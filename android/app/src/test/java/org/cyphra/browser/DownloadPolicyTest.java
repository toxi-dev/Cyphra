/* MPL-2.0. Server download metadata must stay useful without choosing local paths. */
package org.cyphra.browser;

import org.junit.Test;
import static org.junit.Assert.*;

public final class DownloadPolicyTest {
    @Test public void usesDispositionAndDeclaredMime() {
        DownloadPolicy.Metadata result = DownloadPolicy.derive("https://example.org/download?id=42",
            "attachment; filename=\"Quarterly report.pdf\"", "Application/PDF; charset=binary");
        assertEquals("Quarterly report.pdf", result.filename);
        assertEquals("application/pdf", result.mimeType);
        assertEquals("report.pdf", DownloadPolicy.derive("https://example.org/download", "attachment; filename=report", "application/pdf").filename);
    }
    @Test public void utf8FilenameWinsAndPlusStaysLiteral() {
        assertEquals("Prüfung+2026.pdf", DownloadPolicy.derive("https://example.org/fallback",
            "attachment; filename=legacy.pdf; filename*=UTF-8'en'Pr%C3%BCfung+2026.pdf", "application/pdf").filename);
        assertEquals("semi_colon.pdf", DownloadPolicy.derive("https://example.org/fallback",
            "attachment; filename=\"semi;colon.pdf\"", "application/pdf").filename);
    }
    @Test public void invalidExtendedFilenameFallsBack() {
        for (String value : new String[]{"UTF-8''broken%", "UTF-8''broken%C3%28", "UTF-8''broken%FF", "UTF-16''file.pdf"})
            assertEquals("safe.pdf", DownloadPolicy.derive("https://example.org/fallback",
                "attachment; filename=safe.pdf; filename*=" + value, "application/pdf").filename);
    }
    @Test public void urlFallbackExcludesQueryAndDecodesPath() {
        assertEquals("report 2026+final.pdf", DownloadPolicy.derive("https://example.org/files/report%202026+final.pdf?secret=x#fragment", null, "application/pdf").filename);
        assertEquals("download.pdf", DownloadPolicy.derive("https://example.org/?name=wrong.exe", null, "application/pdf").filename);
        assertEquals("download", DownloadPolicy.derive("invalid URL", null, null).filename);
    }
    @Test public void stripsPathsControlsAndDirectionOverrides() {
        assertEquals("report.pdf", DownloadPolicy.derive("https://example.org/download",
            "attachment; filename*=UTF-8''..%2F..%5Creport.pdf", "application/pdf").filename);
        assertEquals("private.txt", DownloadPolicy.derive("https://example.org/download", "attachment; filename=.private.txt", "text/plain").filename);
        assertEquals("report_exe.pdf", DownloadPolicy.derive("https://example.org/download",
            "attachment; filename*=UTF-8''report%E2%80%AEexe.pdf", "application/pdf").filename);
        assertEquals("download.pdf", DownloadPolicy.derive("https://example.org/download",
            "attachment; filename=evil.pdf\r\nInjected: yes", "application/pdf").filename);
    }
    @Test public void limitsLengthAndRetainsExistingExtension() {
        String longName = "r".repeat(300) + ".pdf";
        String result = DownloadPolicy.derive("https://example.org/download", "attachment; filename=" + longName, "application/pdf").filename;
        assertEquals(120, result.codePointCount(0, result.length()));
        assertTrue(result.endsWith(".pdf"));
        String unicode = DownloadPolicy.derive("https://example.org/download", "attachment; filename=" + "文".repeat(200) + ".pdf", "application/pdf").filename;
        assertTrue(unicode.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= 240);
        assertTrue(unicode.endsWith(".pdf"));
        assertEquals("payload.pdf.exe", DownloadPolicy.derive("https://example.org/download", "attachment; filename=payload.pdf.exe", "application/pdf").filename);
    }
    @Test public void invalidMimeIsConservative() {
        for (String value : new String[]{null, "*/*", "application/pdf, text/html", "application/pdf\r\nInjected: yes", "not-a-mime"})
            assertEquals("application/octet-stream", DownloadPolicy.derive("https://example.org/file", null, value).mimeType);
        assertEquals("application/vnd.example+json", DownloadPolicy.derive("https://example.org/file", null, "application/vnd.example+json; version=1").mimeType);
    }
}
