#include <windows.h>
#include <cwchar>
#include <string>

// Skip argv[0] and its first separator, retaining whitespace within the supplied tail.
static const wchar_t* argument_tail(const wchar_t* command) {
    bool quoted = false;
    while (*command) {
        if (*command == L'"') quoted = !quoted;
        if (!quoted && (*command == L' ' || *command == L'\t')) return command + 1;
        ++command;
    }
    return command;
}

// Query in this process so the report includes any per-launch overrides.
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    wchar_t user_region[LOCALE_NAME_MAX_LENGTH]{}, system_region[LOCALE_NAME_MAX_LENGTH]{};
    wchar_t user_language[LOCALE_NAME_MAX_LENGTH]{}, system_language[LOCALE_NAME_MAX_LENGTH]{};
    DYNAMIC_TIME_ZONE_INFORMATION zone{};
    if (!GetUserDefaultLocaleName(user_region, LOCALE_NAME_MAX_LENGTH) ||
        !GetSystemDefaultLocaleName(system_region, LOCALE_NAME_MAX_LENGTH) ||
        !LCIDToLocaleName(GetUserDefaultUILanguage(), user_language, LOCALE_NAME_MAX_LENGTH, 0) ||
        !LCIDToLocaleName(GetSystemDefaultUILanguage(), system_language, LOCALE_NAME_MAX_LENGTH, 0) ||
        GetDynamicTimeZoneInformation(&zone) == TIME_ZONE_ID_INVALID) {
        wchar_t error[256]{};
        swprintf_s(error, L"Could not read Windows locale settings (error %lu).", GetLastError());
        MessageBoxW(nullptr, error, L"Current locale settings", MB_OK | MB_ICONERROR);
        return 1;
    }

    SYSTEMTIME local{};
    GetLocalTime(&local);
    wchar_t report[1024]{};
    swprintf_s(report,
               L"User region: %ls\nSystem region: %ls\n\n"
               L"ANSI code page: %u\nOEM code page: %u\n\n"
               L"User UI language: %ls\nSystem UI language: %ls\n\n"
               L"Time zone: %ls\nLocal time: %04u-%02u-%02u %02u:%02u:%02u",
               user_region, system_region, GetACP(), GetOEMCP(), user_language, system_language,
               zone.TimeZoneKeyName[0] ? zone.TimeZoneKeyName : zone.StandardName,
               local.wYear, local.wMonth, local.wDay, local.wHour, local.wMinute, local.wSecond);
    TOKEN_ELEVATION elevation{};
    DWORD size{};
    const wchar_t* elevated = L"Unknown";
    if (GetTokenInformation(GetCurrentProcessToken(), TokenElevation, &elevation, sizeof(elevation), &size)) {
        elevated = elevation.TokenIsElevated ? L"Yes" : L"No";
    }
    const wchar_t* arguments = argument_tail(GetCommandLineW());
    std::wstring details = report;
    details += L"\n\nElevated: ";
    details += elevated;
    DWORD capacity = GetCurrentDirectoryW(0, nullptr);
    std::wstring directory(capacity, L'\0');
    DWORD length = GetCurrentDirectoryW(capacity, directory.data());
    details += L"\nWorking directory: ";
    if (length && length < capacity) details.append(directory, 0, length);
    else details += L"Unknown";
    details += L"\nAdditional arguments: ";
    details += *arguments ? arguments : L"(none)";
    MessageBoxW(nullptr, details.c_str(), L"Current locale settings", MB_OK | MB_ICONINFORMATION);
    return 0;
}
