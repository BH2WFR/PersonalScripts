// Build as an x86 or x64 console program. Run in a disposable directory.
#include <windows.h>
#include <cstdio>

int wmain() {
    wchar_t region[LOCALE_NAME_MAX_LENGTH]{};
    GetUserDefaultLocaleName(region, LOCALE_NAME_MAX_LENGTH);
    DYNAMIC_TIME_ZONE_INFORMATION zone{};
    GetDynamicTimeZoneInformation(&zone);
    wchar_t decoded[4]{};
    MultiByteToWideChar(CP_ACP, 0, "\x93\xfa", 2, decoded, 4); // CP932 for 日
    wchar_t utf8[4]{};
    MultiByteToWideChar(CP_ACP, 0, "\xe6\x97\xa5", 3, utf8, 4);
    SYSTEMTIME local{}, utc{}, converted{};
    GetSystemTime(&utc);
    GetLocalTime(&local);
    SystemTimeToTzSpecificLocalTime(nullptr, &utc, &converted);
    FILE* file = nullptr;
    if (_wfopen_s(&file, L"locale-probe.txt", L"w, ccs=UTF-8")) return 1;
    wchar_t resource[80]{};
    LoadStringW(nullptr, 1, resource, 80);
    wchar_t preferred[512]{};
    ULONG count{}, size = 512;
    GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, &count, preferred, &size);
    fwprintf(file, L"%ls\n%u\n%04x\n%ls\n%04x\n%04x\n%u\n%u\n%ls\n%ls\n%ls\n",
             region, GetACP(), GetUserDefaultUILanguage(), zone.TimeZoneKeyName,
             decoded[0], utf8[0], local.wHour, converted.wHour, preferred, resource, GetCommandLineW());
    return fclose(file) != 0;
}
