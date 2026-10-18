/* This Source Code Form is subject to the Mozilla Public License, v. 2.0.
 * See https://mozilla.org/MPL/2.0/.
 *
 * Local installer maintenance only. There is no network code, update service,
 * telemetry, process killing or user-profile migration in this helper. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <tlhelp32.h>
#include <bcrypt.h>
#include <wchar.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PATH_LIMIT 32768
#define MANIFEST L".cyphra-install-manifest"
#define MAX_MANIFEST (16 * 1024 * 1024)
#ifdef CYPHRA_HOME_EDITION
#define UPDATE_MUTEX L"Local\\CyphraHomeInstallationUpdate"
#define PROFILE_ROOT L"\\CyphraHome\\Profile"
#define EXPECTED_EDITION "home"
#define EXPECTED_VENDOR "Vendor=Cyphra"
#elif defined(CYPHRA_PUBLIC_EDITION)
#define UPDATE_MUTEX L"Local\\CyphraPublicInstallationUpdate"
#define PROFILE_ROOT L"\\Cyphra\\Profile"
#define EXPECTED_EDITION "public"
#define EXPECTED_VENDOR "Vendor=Cyphra"
#else
#define UPDATE_MUTEX L"Local\\ByteTeamCyphraInstallationUpdate"
#define PROFILE_ROOT L"\\ByteTeam\\Cyphra\\Profile"
#define EXPECTED_EDITION "team"
#define EXPECTED_VENDOR "Vendor=Byte Team"
#endif

typedef struct {
    wchar_t *path;
    unsigned char digest[32];
} ManifestEntry;

typedef struct {
    ManifestEntry *entries;
    size_t count;
    unsigned int version[3];
    int exists;
} FileManifest;
#include "legacy-files.h"

static int legacy_version(const wchar_t *installation, unsigned int version[3]);

static int failure(const wchar_t *message) {
#ifdef CYPHRA_HEADLESS_TEST
    fwprintf(stderr, L"%ls\n", message);
#else
    MessageBoxW(NULL, message, L"Cyphra update", MB_OK | MB_ICONERROR);
#endif
    return 1;
}

static int concatenate(wchar_t output[PATH_LIMIT], const wchar_t *directory, const wchar_t *relative) {
    if (wcslen(directory) + wcslen(relative) + 2 >= PATH_LIMIT) return 0;
    wcscpy(output, directory); wcscat(output, L"\\"); wcscat(output, relative);
    return 1;
}

static int regular_path(const wchar_t *path, int directory) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_REPARSE_POINT)
        && !!(attributes & FILE_ATTRIBUTE_DIRECTORY) == !!directory;
}

static int safe_relative(const wchar_t *path) {
    if (!path[0] || path[0] == L'\\' || path[0] == L'/') return 0;
    const wchar_t *start = path;
    for (const wchar_t *cursor = path;; cursor++) {
        wchar_t c = *cursor;
        if (c && (c < 32 || c == L':' || c == L'/' || c == L'"' || c == L'<' || c == L'>' || c == L'|' || c == L'?' || c == L'*')) return 0;
        if (c == L'\\' || !c) {
            size_t length = (size_t)(cursor - start);
            if (!length || (length == 1 && start[0] == L'.') || (length == 2 && start[0] == L'.' && start[1] == L'.')
                || start[length - 1] == L'.' || start[length - 1] == L' ') return 0;
            size_t base_length = 0;
            while (base_length < length && start[base_length] != L'.') base_length++;
            if ((base_length == 3 && (!_wcsnicmp(start, L"CON", 3) || !_wcsnicmp(start, L"PRN", 3) || !_wcsnicmp(start, L"AUX", 3) || !_wcsnicmp(start, L"NUL", 3)))
                || (base_length == 4 && (!_wcsnicmp(start, L"COM", 3) || !_wcsnicmp(start, L"LPT", 3)) && start[3] >= L'0' && start[3] <= L'9')) return 0;
            if (!c) return 1;
            start = cursor + 1;
        }
    }
}

static int parse_version(const char *text, unsigned int version[3]) {
    for (int component = 0; component < 3; component++) {
        unsigned int value = 0;
        int digits = 0;
        int leading_zero = *text == '0';
        while (*text >= '0' && *text <= '9') {
            value = value * 10 + (unsigned int)(*text++ - '0');
            if (++digits > 4 || value > 9999 || (leading_zero && digits > 1)) return 0;
        }
        if (!digits || (component < 2 ? *text++ != '.' : *text != '\0')) return 0;
        version[component] = value;
    }
    return 1;
}

static int compare_version(const unsigned int left[3], const unsigned int right[3]) {
    for (int i = 0; i < 3; i++) {
        if (left[i] > right[i]) return 1;
        if (left[i] < right[i]) return -1;
    }
    return 0;
}

static void free_manifest(FileManifest *manifest) {
    for (size_t i = 0; i < manifest->count; i++) free(manifest->entries[i].path);
    free(manifest->entries);
    memset(manifest, 0, sizeof(*manifest));
}

static char *read_file(const wchar_t *path, size_t limit) {
    if (!regular_path(path, 0)) return NULL;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    LARGE_INTEGER size;
    if (!GetFileSizeEx(file, &size) || size.QuadPart < 0 || size.QuadPart > (LONGLONG)limit) { CloseHandle(file); return NULL; }
    char *data = calloc((size_t)size.QuadPart + 1, 1);
    DWORD copied = 0;
    if (!data || !ReadFile(file, data, (DWORD)size.QuadPart, &copied, NULL) || copied != size.QuadPart
        || memchr(data, '\0', copied)) { free(data); data = NULL; }
    CloseHandle(file);
    return data;
}

static int hexadecimal(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static int read_manifest(const wchar_t *directory, FileManifest *manifest, int required) {
    wchar_t path[PATH_LIMIT];
    if (!concatenate(path, directory, MANIFEST)) return 0;
    DWORD attributes = GetFileAttributesW(path);
    if (attributes == INVALID_FILE_ATTRIBUTES && GetLastError() == ERROR_FILE_NOT_FOUND && !required) return 1;
    char *data = read_file(path, MAX_MANIFEST);
    if (!data) return 0;
    char *position = data;
    char *newline = strchr(position, '\n');
    if (!newline) { free(data); return 0; }
    *newline = '\0';
    if (strcmp(position, "Cyphra manifest 1")) { free(data); return 0; }
    position = newline + 1; newline = strchr(position, '\n');
    if (!newline) { free(data); return 0; }
    *newline = '\0';
    if (strncmp(position, "version=", 8) || !parse_version(position + 8, manifest->version)) { free(data); return 0; }
    position = newline + 1;
    while (*position) {
        newline = strchr(position, '\n');
        if (!newline) { free(data); return 0; }
        *newline = '\0';
        if (strlen(position) < 66 || position[64] != ' ') { free(data); return 0; }
        ManifestEntry entry = {0};
        for (size_t i = 0; i < 32; i++) {
            int high = hexadecimal(position[i * 2]), low = hexadecimal(position[i * 2 + 1]);
            if (high < 0 || low < 0) { free(data); return 0; }
            entry.digest[i] = (unsigned char)((high << 4) | low);
        }
        int needed = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, position + 65, -1, NULL, 0);
        if (needed < 2 || needed >= PATH_LIMIT) { free(data); return 0; }
        entry.path = calloc((size_t)needed, sizeof(wchar_t));
        if (!entry.path || !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, position + 65, -1, entry.path, needed)) { free(entry.path); free(data); return 0; }
        for (wchar_t *cursor = entry.path; *cursor; cursor++) if (*cursor == L'/') *cursor = L'\\';
        if (!safe_relative(entry.path) || !_wcsicmp(entry.path, MANIFEST)) { free(entry.path); free(data); return 0; }
        for (size_t i = 0; i < manifest->count; i++) {
            if (!_wcsicmp(manifest->entries[i].path, entry.path)) { free(entry.path); free(data); return 0; }
        }
        ManifestEntry *grown = realloc(manifest->entries, (manifest->count + 1) * sizeof(ManifestEntry));
        if (!grown) { free(entry.path); free(data); return 0; }
        manifest->entries = grown;
        manifest->entries[manifest->count++] = entry;
        position = newline + 1;
    }
    free(data);
    unsigned int metadata_version[3];
    if (!legacy_version(directory, metadata_version) || compare_version(metadata_version, manifest->version)) return 0;
    manifest->exists = 1;
    return manifest->count > 0;
}

static int manifest_contains(const FileManifest *manifest, const wchar_t *relative) {
    if (!_wcsicmp(relative, MANIFEST) || !_wcsicmp(relative, L"Uninstall Cyphra.exe")) return 1;
    for (size_t i = 0; i < manifest->count; i++) if (!_wcsicmp(relative, manifest->entries[i].path)) return 1;
    return 0;
}

static int hash_matches(const wchar_t *file, const unsigned char expected[32]) {
    if (!regular_path(file, 0)) return 0;
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    HANDLE input = INVALID_HANDLE_VALUE;
    unsigned char actual[32], buffer[65536];
    int result = 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0) goto finish;
    if (BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) < 0) goto finish;
    input = CreateFileW(file, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (input == INVALID_HANDLE_VALUE) goto finish;
    for (;;) {
        DWORD count;
        if (!ReadFile(input, buffer, sizeof(buffer), &count, NULL)) goto finish;
        if (!count) break;
        if (BCryptHashData(hash, buffer, count, 0) < 0) goto finish;
    }
    if (BCryptFinishHash(hash, actual, sizeof(actual), 0) < 0) goto finish;
    result = memcmp(actual, expected, sizeof(actual)) == 0;
finish:
    if (input != INVALID_HANDLE_VALUE) CloseHandle(input);
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return result;
}

static int running_cyphra(const wchar_t *installation) {
    wchar_t runtime[PATH_LIMIT], launcher[PATH_LIMIT];
    if (!concatenate(runtime, installation, L"runtime\\") || !concatenate(launcher, installation, L"Cyphra.exe")) return 1;
    size_t prefix_length = wcslen(runtime);
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return 1;
    PROCESSENTRY32W entry = {0}; entry.dwSize = sizeof(entry);
    int found = 0;
    if (Process32FirstW(snapshot, &entry)) do {
        HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, entry.th32ProcessID);
        if (!process) continue;
        wchar_t executable[PATH_LIMIT]; DWORD size = PATH_LIMIT;
        if (QueryFullProcessImageNameW(process, 0, executable, &size)
            && (!_wcsnicmp(executable, runtime, prefix_length) || !_wcsicmp(executable, launcher))) found = 1;
        CloseHandle(process);
        if (found) break;
    } while (Process32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    return found;
}

static int legacy_version(const wchar_t *installation, unsigned int version[3]) {
    wchar_t path[PATH_LIMIT];
    if (!concatenate(path, installation, L"cyphra.json")) return 0;
    char *data = read_file(path, 65536);
    if (!data) return 0;
    char *position = strstr(data, "\"version\"");
    int result = 0;
    if (position) {
        position += 9;
        while (*position == ' ' || *position == '\t' || *position == '\r' || *position == '\n') position++;
        if (*position++ == ':') {
            while (*position == ' ' || *position == '\t' || *position == '\r' || *position == '\n') position++;
            if (*position++ == '"') {
                char *end = strchr(position, '"');
                if (end) { *end = '\0'; result = parse_version(position, version); }
            }
        }
    }
    free(data);
    return result;
}

static int recognize_native_gecko_installation(const wchar_t *installation, FileManifest *previous) {
    wchar_t launcher[PATH_LIMIT], engine[PATH_LIMIT], app_ini[PATH_LIMIT], bootstrap[PATH_LIMIT];

    if (!concatenate(launcher, installation, L"Cyphra.exe")
        || !concatenate(engine, installation, L"runtime\\librewolf.exe")
        || !concatenate(app_ini, installation, L"runtime\\browser\\application.ini")
        || !concatenate(bootstrap, installation, L"runtime\\cyphra\\browser\\bootstrap.js")) return 0;

    if (!regular_path(launcher, 0)
        || !regular_path(engine, 0)
        || !regular_path(app_ini, 0)
        || !regular_path(bootstrap, 0)) return 0;

    char *metadata = read_file(app_ini, 65536);
    if (!metadata) return 0;

    int branded =
        strstr(metadata, EXPECTED_VENDOR)
        && strstr(metadata, "Name=Cyphra")
        && strstr(metadata, "RemotingName=cyphra");

    free(metadata);

    if (!branded) return 0;

    /*
     * Native Cyphra development builds existed before installation manifests
     * were introduced. Strong Cyphra-specific anchors above are required so
     * arbitrary folders are never treated as browser installations.
     *
     * Their Cyphra release version is unknown, so treat it as an old build.
     * The normal preservation logic will retain unrelated user-created files
     * while replacing overlapping browser files with the new package.
     */
    previous->version[0] = 0;
    previous->version[1] = 0;
    previous->version[2] = 0;

    return 1;
}

static int recognize_electron_prototype(const wchar_t *installation, FileManifest *previous) {
    size_t count = sizeof(legacy_entries) / sizeof(legacy_entries[0]);
    int anchors = 0;
    for (size_t i = 0; i < count; i++) {
        if (!_wcsicmp(legacy_entries[i].path, L"Cyphra.exe") || !_wcsicmp(legacy_entries[i].path, L"resources\\app.asar")) {
            wchar_t file[PATH_LIMIT];
            if (!concatenate(file, installation, legacy_entries[i].path) || !hash_matches(file, legacy_entries[i].digest)) return 0;
            anchors++;
        }
    }
    if (anchors != 2) return 0;
    previous->entries = calloc(count, sizeof(ManifestEntry));
    if (!previous->entries) return 0;
    for (size_t i = 0; i < count; i++) {
        previous->entries[i].path = _wcsdup(legacy_entries[i].path);
        if (!previous->entries[i].path) return 0;
        memcpy(previous->entries[i].digest, legacy_entries[i].digest, 32);
        previous->count++;
    }
    previous->version[0] = 0; previous->version[1] = 1; previous->version[2] = 0;
    previous->exists = 1;
    return 1;
}

static int safe_installation_path(const wchar_t *input, wchar_t output[PATH_LIMIT]) {
    DWORD length = GetFullPathNameW(input, PATH_LIMIT, output, NULL);
    if (!length || length >= PATH_LIMIT || wcslen(output) < 7) return 0;
    if (output[1] != L':' || output[2] != L'\\' || output[wcslen(output) - 1] == L'\\') return 0;
    wchar_t probe[PATH_LIMIT]; wcscpy(probe, output);
    for (wchar_t *cursor = probe + 3;; cursor++) {
        if (*cursor == L'\\' || !*cursor) {
            wchar_t saved = *cursor; *cursor = L'\0';
            DWORD attributes = GetFileAttributesW(probe);
            *cursor = saved;
            if (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) return 0;
            if (!saved) break;
        }
    }
    return 1;
}

static int directory_empty(const wchar_t *directory) {
    wchar_t pattern[PATH_LIMIT];
    if (!concatenate(pattern, directory, L"*")) return 0;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW(pattern, &data);
    if (find == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_FILE_NOT_FOUND;
    int empty = 1;
    do {
        if (wcscmp(data.cFileName, L".") && wcscmp(data.cFileName, L"..")) { empty = 0; break; }
    } while (FindNextFileW(find, &data));
    FindClose(find);
    return empty;
}

static int edition_matches(const wchar_t *directory, int required) {
    wchar_t path[PATH_LIMIT];
    if (!concatenate(path, directory, L"cyphra.json")) return 0;
    char *data = read_file(path, 65536);
    if (!data) return !required && (strcmp(EXPECTED_EDITION, "home") || directory_empty(directory));
    char *position = strstr(data, "\"edition\"");
    int result = 0;
    if (!position) result = !strcmp(EXPECTED_EDITION, "team");
    else {
        position += strlen("\"edition\"");
        while (*position == ' ' || *position == '\t' || *position == '\r' || *position == '\n') position++;
        if (*position++ == ':') {
            while (*position == ' ' || *position == '\t' || *position == '\r' || *position == '\n') position++;
            if (*position++ == '"') {
                size_t length = strlen(EXPECTED_EDITION);
                result = !strncmp(position, EXPECTED_EDITION, length) && position[length] == '"';
            }
        }
    }
    free(data);
    return result;
}

/* The launcher shares a read handle with its engine. Hold exclusive handles
 * for both profiles through activation, including engines started from another
 * portable copy of this edition. No profile contents are read or changed. */
static int lock_profiles(HANDLE locks[2]) {
    wchar_t local_data[MAX_PATH], profile[PATH_LIMIT], lock_path[PATH_LIMIT];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, SHGFP_TYPE_CURRENT, local_data))) return 0;
    for (size_t i = 0; i < 2; i++) {
        if (swprintf(profile, PATH_LIMIT, L"%ls%ls%ls", local_data, PROFILE_ROOT, i ? L"-Personal" : L"") < 0
            || !concatenate(lock_path, profile, L".cyphra-update.lock")) return 0;
        locks[i] = CreateFileW(lock_path, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (locks[i] == INVALID_HANDLE_VALUE) {
            DWORD error = GetLastError();
            if (error != ERROR_PATH_NOT_FOUND && error != ERROR_FILE_NOT_FOUND) return 0;
        }
    }
    return 1;
}

static int check_current(const wchar_t *installation, const unsigned int incoming[3], FileManifest *previous) {
    DWORD attributes = GetFileAttributesW(installation);
    if (attributes == INVALID_FILE_ATTRIBUTES && GetLastError() == ERROR_FILE_NOT_FOUND) return 0;
    if (attributes == INVALID_FILE_ATTRIBUTES && GetLastError() == ERROR_PATH_NOT_FOUND) return 0;
    if (!regular_path(installation, 1)) return failure(L"The application folder is not a regular directory. Choose another installation folder.");
    if (running_cyphra(installation)) return failure(L"Close every Cyphra window in Work and Personal mode before installing this update.");
    if (!edition_matches(installation, 0)) return failure(L"This folder belongs to a different Cyphra edition. Install editions separately.");
    if (!read_manifest(installation, previous, 0)) return failure(L"The existing installation-file manifest is invalid. No application or profile files were changed.");
    if (!previous->exists && !legacy_version(installation, previous->version) && !directory_empty(installation)
        && !recognize_native_gecko_installation(installation, previous)
        && !recognize_electron_prototype(installation, previous)) return failure(L"This folder contains files that are not a recognized Cyphra installation. Choose another folder or move those files elsewhere.");
    if (compare_version(incoming, previous->version) < 0) return failure(L"This installer is older than the installed Cyphra release. Downgrades are refused to protect your Gecko profile.");
    return 0;
}

static int enumerate_tree(const wchar_t *root, const wchar_t *relative, const wchar_t *new_root,
                          const FileManifest *previous, const FileManifest *incoming, int mode) {
    /* Directory traversal recurses without large stack buffers. Windows' GUI
     * executable stack must also accommodate deeply nested engine directories. */
    typedef struct { wchar_t directory[PATH_LIMIT], pattern[PATH_LIMIT], child[PATH_LIMIT], source[PATH_LIMIT], target[PATH_LIMIT]; } Paths;
    Paths *paths = calloc(1, sizeof(Paths));
    if (!paths) return 0;
    if (relative[0]) { if (!concatenate(paths->directory, root, relative)) { free(paths); return 0; } }
    else wcscpy(paths->directory, root);
    if (!concatenate(paths->pattern, paths->directory, L"*")) { free(paths); return 0; }
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW(paths->pattern, &data);
    if (find == INVALID_HANDLE_VALUE) { int empty = GetLastError() == ERROR_FILE_NOT_FOUND; free(paths); return empty; }
    int result = 1;
    do {
        if (!wcscmp(data.cFileName, L".") || !wcscmp(data.cFileName, L"..")) continue;
        wchar_t *child = paths->child, *source = paths->source, *target = paths->target;
        if (relative[0]) { if (!concatenate(child, relative, data.cFileName)) { result = 0; break; } }
        else wcscpy(child, data.cFileName);
        if (!safe_relative(child) || (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
            || !concatenate(source, root, child)) { result = 0; break; }
        int is_directory = !!(data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY);
        if (mode == 0) {
            /* Verify the incoming tree contains exactly its manifest plus the
             * uninstaller generated by this NSIS installation. */
            if (is_directory) { if (!enumerate_tree(root, child, NULL, NULL, incoming, mode)) { result = 0; break; } }
            else if (!manifest_contains(incoming, child)) { result = 0; break; }
        } else if (mode == 1) {
            if (!concatenate(target, new_root, child)) { result = 0; break; }
            if (is_directory) {
                DWORD attributes = GetFileAttributesW(target);
                if (attributes == INVALID_FILE_ATTRIBUTES && !CreateDirectoryW(target, NULL)) { result = 0; break; }
                if (!regular_path(target, 1) || !enumerate_tree(root, child, new_root, previous, incoming, mode)) { result = 0; break; }
            } else if (!manifest_contains(previous, child)) {
                DWORD attributes = GetFileAttributesW(target);
                if (attributes != INVALID_FILE_ATTRIBUTES) {
                    /* A manifest-less 0.2 installation predates shipped-file
                     * tracking. Its overlapping app files are replaced, while
                     * non-overlapping files remain conservatively preserved. */
                    if (previous->exists) { result = 0; break; }
                } else if (!CopyFileW(source, target, TRUE)) { result = 0; break; }
            }
        } else {
            if (is_directory) {
                if (!enumerate_tree(root, child, NULL, NULL, NULL, mode) || !RemoveDirectoryW(source)) { result = 0; break; }
            } else {
                SetFileAttributesW(source, FILE_ATTRIBUTE_NORMAL);
                if (!DeleteFileW(source)) { result = 0; break; }
            }
        }
    } while (FindNextFileW(find, &data));
    if (result && GetLastError() != ERROR_NO_MORE_FILES) result = 0;
    FindClose(find);
    free(paths);
    return result;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous_instance, PWSTR command, int show) {
    (void)instance; (void)previous_instance; (void)command; (void)show;
    int argc;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return failure(L"Cyphra could not read the updater arguments.");
    int result = 1;
    wchar_t installation[PATH_LIMIT], staged[PATH_LIMIT], backup[PATH_LIMIT];
    FileManifest previous = {0}, incoming = {0};
    unsigned int expected[3]; char expected_text[64];
    HANDLE mutex = NULL, profile_locks[2] = { INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE };
    if ((argc != 4 && argc != 5) || (wcscmp(argv[1], L"--check") && wcscmp(argv[1], L"--commit"))
        || !safe_installation_path(argv[2], installation)) { failure(L"Cyphra received an invalid local update request."); goto done; }
    const wchar_t *version_argument = argv[argc - 1];
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, version_argument, -1, expected_text, sizeof(expected_text), NULL, NULL)
        || !parse_version(expected_text, expected)) { failure(L"The incoming Cyphra version is invalid."); goto done; }
    mutex = CreateMutexW(NULL, FALSE, UPDATE_MUTEX);
    DWORD acquired = mutex ? WaitForSingleObject(mutex, 0) : WAIT_FAILED;
    if (acquired != WAIT_OBJECT_0 && acquired != WAIT_ABANDONED) { failure(L"Another Cyphra installation or update is already running."); goto done; }
    if (!lock_profiles(profile_locks)) { failure(L"Close every Work and Personal window before installing this Cyphra update."); goto done; }
    if (check_current(installation, expected, &previous)) goto done;
    if (!wcscmp(argv[1], L"--check")) {
        if (argc != 4) { failure(L"Invalid installer check arguments."); goto done; }
        result = 0; goto done;
    }
    if (argc != 5 || !safe_installation_path(argv[3], staged) || !_wcsicmp(installation, staged)) { failure(L"The new application staging folder is invalid."); goto done; }
    if (!edition_matches(staged, 1)) { failure(L"This package belongs to a different Cyphra edition. Install editions separately."); goto done; }
    wchar_t parent[PATH_LIMIT], stage_parent[PATH_LIMIT];
    wcscpy(parent, installation); wcscpy(stage_parent, staged);
    wchar_t *separator = wcsrchr(parent, L'\\'), *stage_separator = wcsrchr(stage_parent, L'\\');
    if (!separator || !stage_separator) goto done;
    *separator = L'\0'; *stage_separator = L'\0';
    if (_wcsicmp(parent, stage_parent) || !regular_path(staged, 1) || !read_manifest(staged, &incoming, 1)
        || compare_version(incoming.version, expected) || !enumerate_tree(staged, L"", NULL, NULL, &incoming, 0)) {
        failure(L"The staged application does not match this Cyphra installer. Your installed browser was left unchanged."); goto done;
    }
    for (size_t i = 0; i < incoming.count; i++) {
        wchar_t file[PATH_LIMIT];
        if (!concatenate(file, staged, incoming.entries[i].path) || !hash_matches(file, incoming.entries[i].digest)) {
            failure(L"A new application file failed its SHA-256 integrity check. The installed browser and your profile were left unchanged."); goto done;
        }
    }
    if (previous.exists || regular_path(installation, 1)) {
        if (!enumerate_tree(installation, L"", staged, &previous, &incoming, 1)) {
            failure(L"An unknown file in the application folder could not be preserved, or conflicts with the new package. Move it outside the application folder and try again. Your current browser was left unchanged."); goto done;
        }
    }
    if (running_cyphra(installation)) { failure(L"Cyphra started during the update. Close it and try again. No installed application files were changed."); goto done; }
    if (!GetTempFileNameW(parent, L"cyp", 0, backup) || !DeleteFileW(backup)) { failure(L"Cyphra could not reserve a rollback folder beside the installation."); goto done; }
    int had_installation = regular_path(installation, 1);
    if (had_installation && !MoveFileExW(installation, backup, MOVEFILE_WRITE_THROUGH)) {
        failure(L"Cyphra could not move the current application into its rollback folder. Close Cyphra and check folder permissions. The current installation was left unchanged."); goto done;
    }
    if (!MoveFileExW(staged, installation, MOVEFILE_WRITE_THROUGH)) {
        if (had_installation && !MoveFileExW(backup, installation, MOVEFILE_WRITE_THROUGH)) {
            wchar_t warning[PATH_LIMIT];
            swprintf(warning, PATH_LIMIT, L"Cyphra could not activate the new application or restore the old folder. The old application remains in:\n%s\n\nYour profile was not changed. Restore that folder to the installation location before launching Cyphra.", backup);
            failure(warning);
        } else failure(L"Cyphra could not activate the new application. The previous application was restored and your profile was left unchanged.");
        goto done;
    }
    if (had_installation && (!enumerate_tree(backup, L"", NULL, NULL, NULL, 2) || !RemoveDirectoryW(backup))) {
        wchar_t warning[PATH_LIMIT];
        swprintf(warning, PATH_LIMIT, L"The Cyphra update was installed, but Windows could not remove its old application backup:\n%s\n\nYour profile was preserved. You can delete this backup after confirming the new browser runs.", backup);
        MessageBoxW(NULL, warning, L"Cyphra update", MB_OK | MB_ICONINFORMATION);
    }
    result = 0;
done:
    for (size_t i = 0; i < 2; i++) if (profile_locks[i] != INVALID_HANDLE_VALUE) CloseHandle(profile_locks[i]);
    if (mutex) { ReleaseMutex(mutex); CloseHandle(mutex); }
    free_manifest(&previous); free_manifest(&incoming);
    LocalFree(argv);
    return result;
}
