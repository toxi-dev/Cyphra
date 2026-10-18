/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. See https://mozilla.org/MPL/2.0/. */
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
#include <winhttp.h>
#include <wchar.h>
#include <stdlib.h>
#ifdef CYPHRA_HEADLESS_TEST
#include <stdio.h>
#endif

#define COMMAND_LIMIT 32767
#ifdef CYPHRA_HOME_EDITION
#define PROFILE_ROOT L"\\CyphraHome\\Profile"
#define UPDATE_MUTEX L"Local\\CyphraHomeInstallationUpdate"
#define EDITION L"home"
#define REMOTING_ROOT L"cyphra-home-"
#elif defined(CYPHRA_PUBLIC_EDITION)
#define PROFILE_ROOT L"\\Cyphra\\Profile"
#define UPDATE_MUTEX L"Local\\CyphraPublicInstallationUpdate"
#define EDITION L"public"
#define REMOTING_ROOT L"cyphra-public-"
#else
#define PROFILE_ROOT L"\\ByteTeam\\Cyphra\\Profile"
#define UPDATE_MUTEX L"Local\\ByteTeamCyphraInstallationUpdate"
#define EDITION L"team"
#define REMOTING_ROOT L"cyphra-team-"
#endif

static int fail(const wchar_t *message) {
#ifdef CYPHRA_HEADLESS_TEST
    fwprintf(stderr, L"%ls\n", message);
#else
    MessageBoxW(NULL, message, L"Cyphra", MB_OK | MB_ICONERROR);
#endif
    return 1;
}

static int append_char(wchar_t *buffer, size_t *length, wchar_t value) {
    if (*length >= COMMAND_LIMIT - 1) return 0;
    buffer[(*length)++] = value;
    buffer[*length] = L'\0';
    return 1;
}

/* Apply Windows argv quoting, including backslashes before quotes and the
 * closing delimiter. CreateProcess receives an explicit application path. */
static int quote_argument(wchar_t *buffer, size_t *length, const wchar_t *value) {
    if (*length && !append_char(buffer, length, L' ')) return 0;
    if (!append_char(buffer, length, L'"')) return 0;
    size_t slashes = 0;
    for (;;) {
        wchar_t c = *value++;
        if (c == L'\\') { slashes++; continue; }
        size_t count = (c == L'"' || c == L'\0') ? slashes * 2 : slashes;
        if (c == L'"') count++;
        for (size_t i = 0; i < count; i++) if (!append_char(buffer, length, L'\\')) return 0;
        slashes = 0;
        if (c == L'\0') break;
        if (!append_char(buffer, length, c)) return 0;
    }
    return append_char(buffer, length, L'"');
}

static int allowed_url(const wchar_t *url) {
    size_t length = wcslen(url);
    if (length > 16384) return 0;
    for (size_t i = 0; i < length; i++) if (url[i] < 32 || url[i] == 127) return 0;
    URL_COMPONENTS parts = {0};
    parts.dwStructSize = sizeof(parts);
    parts.dwHostNameLength = (DWORD)-1;
    parts.dwUserNameLength = (DWORD)-1;
    parts.dwPasswordLength = (DWORD)-1;
    if (!WinHttpCrackUrl(url, 0, 0, &parts)) return 0;
    return (parts.nScheme == INTERNET_SCHEME_HTTP || parts.nScheme == INTERNET_SCHEME_HTTPS)
        && parts.dwHostNameLength > 0 && parts.dwUserNameLength == 0 && parts.dwPasswordLength == 0;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
    (void)instance; (void)previous; (void)command; (void)show;
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return fail(L"Cyphra could not read its launch arguments.");
    int private_window = 0;
#if defined(CYPHRA_PUBLIC_EDITION) || defined(CYPHRA_HOME_EDITION)
    int personal_mode = 1;
#else
    int personal_mode = 0;
#endif
    for (int i = 1; i < argc; i++) {
        if (!wcscmp(argv[i], L"--work") || !wcscmp(argv[i], L"-work")) {
#ifdef CYPHRA_HOME_EDITION
            LocalFree(argv); return fail(L"Cyphra Home has one everyday browsing profile.");
#else
            personal_mode = 0; continue;
#endif
        }
        if (!wcscmp(argv[i], L"--personal") || !wcscmp(argv[i], L"-personal")) { personal_mode = 1; continue; }
        if (wcscmp(argv[i], L"--private-window") == 0) { private_window = 1; continue; }
        if (!allowed_url(argv[i])) {
            LocalFree(argv);
            return fail(L"Cyphra accepts HTTP or HTTPS addresses, --work, --personal and --private-window. Browser configuration and privileged command-line switches are not accepted.");
        }
    }
    wchar_t executable[32768];
    wchar_t application[32768];
    DWORD copied = GetModuleFileNameW(NULL, executable, 32768);
    if (!copied || copied >= 32768) { LocalFree(argv); return fail(L"Cyphra's installation path is too long."); }
    wchar_t *last = wcsrchr(executable, L'\\');
    if (!last || (size_t)(last - executable) + 40 >= 32768) { LocalFree(argv); return fail(L"Cyphra could not locate its engine."); }
    wcscpy(application, executable);
    wcscpy(application + (last - executable), L"\\runtime\\browser\\application.ini");
    wcscpy(last, L"\\runtime\\librewolf.exe");
    DWORD attrs = GetFileAttributesW(executable);
    if (attrs == INVALID_FILE_ATTRIBUTES || (attrs & FILE_ATTRIBUTE_DIRECTORY)) {
        LocalFree(argv); return fail(L"The native Gecko engine is missing. Reinstall the complete Cyphra package.");
    }
    attrs = GetFileAttributesW(application);
    if (attrs == INVALID_FILE_ATTRIBUTES || (attrs & FILE_ATTRIBUTE_DIRECTORY)) {
        LocalFree(argv); return fail(L"The Cyphra application identity is missing. Reinstall the complete Cyphra package.");
    }
    PWSTR local_app_data = NULL;
    if (FAILED(SHGetKnownFolderPath(&FOLDERID_LocalAppData, KF_FLAG_CREATE, NULL, &local_app_data))) {
        LocalFree(argv); return fail(L"Cyphra could not locate your local application data.");
    }
    const wchar_t *suffix = personal_mode ? PROFILE_ROOT L"-Personal" : PROFILE_ROOT;
    size_t profile_length = wcslen(local_app_data) + wcslen(suffix) + 1;
    wchar_t *profile = calloc(profile_length, sizeof(wchar_t));
    if (!profile) { CoTaskMemFree(local_app_data); LocalFree(argv); return fail(L"Cyphra could not allocate its profile path."); }
    wcscpy(profile, local_app_data); wcscat(profile, suffix);
    CoTaskMemFree(local_app_data);
    int directory_result = SHCreateDirectoryExW(NULL, profile, NULL);
    if (directory_result != ERROR_SUCCESS && directory_result != ERROR_ALREADY_EXISTS && directory_result != ERROR_FILE_EXISTS) {
        free(profile); LocalFree(argv); return fail(L"Cyphra could not create its separate user profile.");
    }
    wchar_t *line = calloc(COMMAND_LIMIT, sizeof(wchar_t));
    if (!line) { free(profile); LocalFree(argv); return fail(L"Cyphra could not allocate its launch command."); }
    size_t used = 0;
    int valid = quote_argument(line, &used, executable)
        && quote_argument(line, &used, L"-app") && quote_argument(line, &used, application)
        && quote_argument(line, &used, L"-profile") && quote_argument(line, &used, profile);
    if (private_window) valid = valid && quote_argument(line, &used, L"-private-window");
    for (int i = 1; valid && i < argc; i++) {
        if (wcscmp(argv[i], L"--private-window") && wcscmp(argv[i], L"--work") && wcscmp(argv[i], L"-work")
            && wcscmp(argv[i], L"--personal") && wcscmp(argv[i], L"-personal")) valid = quote_argument(line, &used, argv[i]);
    }
    LocalFree(argv);
    if (!valid) { free(profile); free(line); return fail(L"Cyphra's launch command is too long. Open fewer addresses at once."); }
    STARTUPINFOEXW startup = {0}; startup.StartupInfo.cb = sizeof(startup);
    PROCESS_INFORMATION process = {0};
    HANDLE update_mutex = CreateMutexW(NULL, FALSE, UPDATE_MUTEX);
    DWORD lock_result = update_mutex ? WaitForSingleObject(update_mutex, 0) : WAIT_FAILED;
    if (lock_result != WAIT_OBJECT_0 && lock_result != WAIT_ABANDONED) {
        if (update_mutex) CloseHandle(update_mutex);
        free(profile); free(line);
        return fail(L"Cyphra is being installed or updated. Wait for the installer to finish before opening the browser.");
    }
    wchar_t *lock_path = calloc(profile_length + 32, sizeof(wchar_t));
    HANDLE profile_lock = INVALID_HANDLE_VALUE;
    if (lock_path) {
        wcscpy(lock_path, profile); wcscat(lock_path, L"\\.cyphra-update.lock");
        SECURITY_ATTRIBUTES security = { sizeof(security), NULL, TRUE };
        profile_lock = CreateFileW(lock_path, GENERIC_READ, FILE_SHARE_READ, &security, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    }
    free(lock_path); free(profile);
    SIZE_T attribute_size = 0;
    InitializeProcThreadAttributeList(NULL, 1, 0, &attribute_size);
    startup.lpAttributeList = malloc(attribute_size);
    int attributes_ready = startup.lpAttributeList && InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &attribute_size);
    int environment_ready = SetEnvironmentVariableW(L"CYPHRA_MODE", personal_mode ? L"personal" : L"work")
        && SetEnvironmentVariableW(L"CYPHRA_EDITION", EDITION)
        && SetEnvironmentVariableW(L"MOZ_APP_REMOTINGNAME", personal_mode ? REMOTING_ROOT L"personal" : REMOTING_ROOT L"work");
    BOOL created = profile_lock != INVALID_HANDLE_VALUE && attributes_ready && environment_ready
        && UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, &profile_lock, sizeof(profile_lock), NULL, NULL)
        && CreateProcessW(executable, line, NULL, NULL, TRUE, CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
                          NULL, NULL, &startup.StartupInfo, &process);
    if (attributes_ready) DeleteProcThreadAttributeList(startup.lpAttributeList);
    free(startup.lpAttributeList);
    if (profile_lock != INVALID_HANDLE_VALUE) CloseHandle(profile_lock);
    ReleaseMutex(update_mutex); CloseHandle(update_mutex);
    free(line);
    if (!created) return fail(L"Cyphra could not start its native Gecko engine. Check the installation and your Windows security policy.");
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    return 0;
}
