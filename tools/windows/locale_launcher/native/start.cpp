#include "profile.h"
#include <shellapi.h>
#include <detours.h>
#include <filesystem>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static DWORD read_profile(wchar_t** args, Profile& p) {
    if ((*args[2] && !IsValidLocaleName(args[2])) ||
        (*args[4] && !IsValidLocaleName(args[4])) ||
        wcscpy_s(p.region, args[2]) || wcscpy_s(p.language, args[4]))
        return ERROR_INVALID_PARAMETER;
    wchar_t* end = nullptr;
    p.page = wcstoul(args[3], &end, 10);
    if (!*args[3] || *end || (p.page && !IsValidCodePage(p.page))) return ERROR_INVALID_PARAMETER;
    if (*args[5]) {
        for (DWORD i = 0; ; ++i) {
            DWORD status = EnumDynamicTimeZoneInformation(i, &p.zone);
            if (status != ERROR_SUCCESS) return status;
            if (_wcsicmp(p.zone.TimeZoneKeyName, args[5]) == 0) break;
        }
    }
    return ERROR_SUCCESS;
}

static DWORD start(wchar_t** args, const wchar_t* arguments, const wchar_t* working_directory) {
    Profile p{};
    DWORD status = read_profile(args, p);
    if (status) return status;
    const fs::path target(args[1]);
    const auto extension = target.extension().wstring();
    if (!target.is_absolute() || (_wcsicmp(extension.c_str(), L".exe") && _wcsicmp(extension.c_str(), L".com")))
        return ERROR_INVALID_PARAMETER;
    std::wstring own_path(32768, L'\0');
    DWORD length = GetModuleFileNameW(nullptr, own_path.data(), static_cast<DWORD>(own_path.size()));
    if (!length || length >= own_path.size()) return ERROR_BAD_PATHNAME;
    own_path.resize(length);
    auto dll = fs::path(own_path).parent_path() / L"locale-settings.dll";
    if (GetFileAttributesW(dll.c_str()) == INVALID_FILE_ATTRIBUTES) return GetLastError();
    // The PE import table holds narrow names. Prefer an ASCII short path when available.
    std::wstring short_path(32768, L'\0');
    length = GetShortPathNameW(dll.c_str(), short_path.data(), static_cast<DWORD>(short_path.size()));
    std::wstring dll_path = length && length < short_path.size() ? short_path.substr(0, length) : dll.wstring();
    BOOL replaced = FALSE;
    bool utf8 = GetACP() == CP_UTF8;
    int bytes = WideCharToMultiByte(CP_ACP, 0, dll_path.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::vector<char> narrow(bytes);
    if (!bytes || !WideCharToMultiByte(CP_ACP, utf8 ? 0 : WC_NO_BEST_FIT_CHARS, dll_path.c_str(), -1,
            narrow.data(), bytes, nullptr, utf8 ? nullptr : &replaced) || replaced)
        return ERROR_NO_UNICODE_TRANSLATION;

    PROCESS_INFORMATION child{};
    STARTUPINFOW startup{sizeof(startup)};
    std::wstring command = L"\"" + target.wstring() + L"\"";
    if (*arguments) {
        command += L' ';
        command += arguments;
    }
    // Only the adjacent, fixed locale provider is used, only at process creation.
    if (!DetourCreateProcessWithDllExW(target.c_str(), command.data(), nullptr, nullptr, FALSE,
        CREATE_SUSPENDED, nullptr, working_directory, &startup, &child, narrow.data(), nullptr))
        return GetLastError();

    wchar_t name[80];
    object_name(name, child.dwProcessId, L"profile");
    HANDLE mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, sizeof(p), name);
    status = mapping ? ERROR_SUCCESS : GetLastError();
    if (mapping && GetLastError() == ERROR_ALREADY_EXISTS) status = ERROR_ALREADY_EXISTS;
    object_name(name, child.dwProcessId, L"ready");
    HANDLE ready = CreateEventW(nullptr, TRUE, FALSE, name);
    if (!ready || GetLastError() == ERROR_ALREADY_EXISTS) status = GetLastError();
    if (!status) {
        auto view = MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, sizeof(p));
        if (view) {
            memcpy(view, &p, sizeof(p));
            UnmapViewOfFile(view);
        } else status = GetLastError();
    }
    if (!status && ResumeThread(child.hThread) == DWORD(-1)) status = GetLastError();
    if (!status) {
        HANDLE signals[]{ready, child.hProcess};
        switch (WaitForMultipleObjects(2, signals, FALSE, 30000)) {
            case WAIT_OBJECT_0: break;
            case WAIT_TIMEOUT: status = ERROR_TIMEOUT; break;
            default: status = ERROR_DLL_INIT_FAILED; break;
        }
    }
    if (status) TerminateProcess(child.hProcess, status);
    if (ready) CloseHandle(ready);
    if (mapping) CloseHandle(mapping);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    return status;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    int argc = 0;
    auto args = CommandLineToArgvW(GetCommandLineW(), &argc);
    DWORD status = ERROR_INVALID_PARAMETER;
    if (args && argc >= 6 && argc <= 8) {
        const auto directory = argc == 8 ? fs::path(args[7]) : fs::path(args[1]).parent_path();
        status = start(args, argc >= 7 ? args[6] : L"", directory.c_str());
    }
    LocalFree(args);
    if (status) {
        wchar_t message[640]{};
        FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, nullptr,
                       status, 0, message, 640, nullptr);
        std::wstring detail = L"Could not start the executable with the selected locale settings.\n\n";
        detail += std::to_wstring(status) + L"  " + message;
        MessageBoxW(nullptr, detail.c_str(), L"Locale Launcher", MB_OK | MB_ICONERROR);
    }
    return static_cast<int>(status);
}
