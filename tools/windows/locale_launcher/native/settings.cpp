#include "profile.h"
#include <detours.h>
#include <string>

namespace {
Profile profile;
LCID region_id;
LANGID ui_id;

// Keep the original entry point for explicit parameters and host defaults.
#define ORIGINAL(api) auto original_##api = &api
ORIGINAL(GetACP); ORIGINAL(GetOEMCP); ORIGINAL(MultiByteToWideChar); ORIGINAL(WideCharToMultiByte);
ORIGINAL(GetCPInfo); ORIGINAL(GetCPInfoExW); ORIGINAL(IsDBCSLeadByteEx); ORIGINAL(IsDBCSLeadByte);
ORIGINAL(CreateFileA); ORIGINAL(GetFileAttributesA); ORIGINAL(MessageBoxA); ORIGINAL(SetWindowTextA);
ORIGINAL(TextOutA); ORIGINAL(GetTextExtentPoint32A);
ORIGINAL(GetUserDefaultLCID); ORIGINAL(GetSystemDefaultLCID); ORIGINAL(GetThreadLocale);
ORIGINAL(GetUserDefaultLangID); ORIGINAL(GetSystemDefaultLangID);
ORIGINAL(GetUserDefaultLocaleName); ORIGINAL(GetSystemDefaultLocaleName);
ORIGINAL(GetLocaleInfoW); ORIGINAL(GetLocaleInfoEx);
ORIGINAL(GetUserDefaultUILanguage); ORIGINAL(GetSystemDefaultUILanguage);
ORIGINAL(GetUserPreferredUILanguages); ORIGINAL(GetSystemPreferredUILanguages);
ORIGINAL(GetDateFormatEx); ORIGINAL(GetTimeFormatEx); ORIGINAL(GetNumberFormatEx);
ORIGINAL(GetTimeZoneInformation); ORIGINAL(GetDynamicTimeZoneInformation); ORIGINAL(GetLocalTime);
ORIGINAL(SystemTimeToTzSpecificLocalTimeEx); ORIGINAL(TzSpecificLocalTimeToSystemTimeEx);
ORIGINAL(SystemTimeToTzSpecificLocalTime); ORIGINAL(TzSpecificLocalTimeToSystemTime);

UINT resolve_page(UINT page) {
    return page == CP_ACP || page == CP_OEMCP || page == CP_THREAD_ACP ? profile.page : page;
}
UINT WINAPI page() { return profile.page; }
int WINAPI decode(UINT cp, DWORD flags, LPCCH src, int size, LPWSTR dst, int space) {
    UINT effective = resolve_page(cp);
    if (effective == CP_UTF8 && cp != effective) flags &= MB_ERR_INVALID_CHARS;
    return original_MultiByteToWideChar(effective, flags, src, size, dst, space);
}
int WINAPI encode(UINT cp, DWORD flags, LPCWCH src, int size, LPSTR dst, int space, LPCCH fallback, LPBOOL used) {
    if (resolve_page(cp) == CP_UTF8 && resolve_page(cp) != cp) {
        if (used) *used = FALSE;
        return original_WideCharToMultiByte(CP_UTF8, flags & WC_ERR_INVALID_CHARS, src, size, dst, space, nullptr, nullptr);
    }
    return original_WideCharToMultiByte(resolve_page(cp), flags, src, size, dst, space, fallback, used);
}
BOOL WINAPI cp_info(UINT cp, LPCPINFO info) { return original_GetCPInfo(resolve_page(cp), info); }
BOOL WINAPI cp_info_ex(UINT cp, DWORD flags, LPCPINFOEXW info) { return original_GetCPInfoExW(resolve_page(cp), flags, info); }
BOOL WINAPI lead_ex(UINT cp, BYTE byte) { return original_IsDBCSLeadByteEx(resolve_page(cp), byte); }
BOOL WINAPI lead(BYTE byte) { return original_IsDBCSLeadByteEx(profile.page, byte); }

std::wstring wide(LPCSTR text) {
    if (!text) return {};
    int size = original_MultiByteToWideChar(profile.page, 0, text, -1, nullptr, 0);
    std::wstring value(size, L'\0');
    if (size) original_MultiByteToWideChar(profile.page, 0, text, -1, value.data(), size);
    return value;
}
HANDLE WINAPI create_file(LPCSTR path, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES security,
                          DWORD creation, DWORD flags, HANDLE pattern) {
    return CreateFileW(path ? wide(path).c_str() : nullptr, access, share, security, creation, flags, pattern);
}
DWORD WINAPI attributes(LPCSTR path) { return GetFileAttributesW(path ? wide(path).c_str() : nullptr); }
int WINAPI message(HWND hwnd, LPCSTR text, LPCSTR title, UINT flags) {
    return MessageBoxW(hwnd, text ? wide(text).c_str() : nullptr, title ? wide(title).c_str() : nullptr, flags);
}
BOOL WINAPI set_text(HWND hwnd, LPCSTR text) { return SetWindowTextW(hwnd, text ? wide(text).c_str() : nullptr); }

// GDI receives a counted byte string, which need not end at a null character.
std::wstring wide_text(LPCSTR text, int length) {
    int size = original_MultiByteToWideChar(profile.page, 0, text, length, nullptr, 0);
    std::wstring value(size, L'\0');
    if (size) original_MultiByteToWideChar(profile.page, 0, text, length, value.data(), size);
    return value;
}
BOOL WINAPI text_out(HDC dc, int x, int y, LPCSTR text, int length) {
    if (!text || length <= 0) return original_TextOutA(dc, x, y, text, length);
    auto value = wide_text(text, length);
    return TextOutW(dc, x, y, value.data(), static_cast<int>(value.size()));
}
BOOL WINAPI text_extent(HDC dc, LPCSTR text, int length, LPSIZE size) {
    if (!text || length <= 0) return original_GetTextExtentPoint32A(dc, text, length, size);
    auto value = wide_text(text, length);
    return GetTextExtentPoint32W(dc, value.data(), static_cast<int>(value.size()), size);
}

LCID WINAPI region() { return region_id; }
LANGID WINAPI region_language() { return LANGIDFROMLCID(region_id); }
LANGID WINAPI language() { return ui_id; }
int WINAPI region_name(LPWSTR buffer, int size) {
    int needed = static_cast<int>(wcslen(profile.region)) + 1;
    if (!buffer || size < needed) { SetLastError(ERROR_INSUFFICIENT_BUFFER); return 0; }
    wcscpy_s(buffer, size, profile.region);
    return needed;
}
int WINAPI locale_info(LCID id, LCTYPE type, LPWSTR data, int size) {
    if (id == LOCALE_USER_DEFAULT || id == LOCALE_SYSTEM_DEFAULT)
        return original_GetLocaleInfoEx(profile.region, type, data, size);
    return original_GetLocaleInfoW(id, type, data, size);
}
LPCWSTR resolve_region(LPCWSTR name) {
    return !name || wcscmp(name, LOCALE_NAME_SYSTEM_DEFAULT) == 0 ? profile.region : name;
}
int WINAPI locale_info_ex(LPCWSTR name, LCTYPE type, LPWSTR data, int size) {
    return original_GetLocaleInfoEx(resolve_region(name), type, data, size);
}
int WINAPI date_format(LPCWSTR name, DWORD flags, const SYSTEMTIME* time, LPCWSTR format,
                       LPWSTR output, int length, LPCWSTR calendar) {
    return original_GetDateFormatEx(resolve_region(name), flags, time, format, output, length, calendar);
}
int WINAPI time_format(LPCWSTR name, DWORD flags, const SYSTEMTIME* time, LPCWSTR format, LPWSTR output, int length) {
    return original_GetTimeFormatEx(resolve_region(name), flags, time, format, output, length);
}
int WINAPI number_format(LPCWSTR name, DWORD flags, LPCWSTR value, const NUMBERFMTW* format, LPWSTR output, int length) {
    return original_GetNumberFormatEx(resolve_region(name), flags, value, format, output, length);
}
BOOL WINAPI preferred_languages(DWORD flags, PULONG count, PWSTR buffer, PULONG capacity) {
    if (!count || !capacity || ((flags & MUI_LANGUAGE_ID) && (flags & MUI_LANGUAGE_NAME))) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    wchar_t id[5]{};
    swprintf_s(id, L"%04x", ui_id);
    LPCWSTR value = flags & MUI_LANGUAGE_ID ? id : profile.language;
    ULONG needed = static_cast<ULONG>(wcslen(value)) + 2;
    ULONG provided = *capacity;
    *capacity = needed;
    *count = 1;
    if (!buffer && !provided) return TRUE;
    if (!buffer || provided < needed) {
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return FALSE;
    }
    memcpy(buffer, value, (needed - 1) * sizeof(wchar_t));
    buffer[needed - 1] = L'\0';
    return TRUE;
}

BOOL WINAPI utc_to_local_ex(const DYNAMIC_TIME_ZONE_INFORMATION* zone, const SYSTEMTIME* utc, SYSTEMTIME* local) {
    return original_SystemTimeToTzSpecificLocalTimeEx(zone ? zone : &profile.zone, utc, local);
}
BOOL WINAPI local_to_utc_ex(const DYNAMIC_TIME_ZONE_INFORMATION* zone, const SYSTEMTIME* local, SYSTEMTIME* utc) {
    return original_TzSpecificLocalTimeToSystemTimeEx(zone ? zone : &profile.zone, local, utc);
}
BOOL WINAPI utc_to_local(const TIME_ZONE_INFORMATION* zone, const SYSTEMTIME* utc, SYSTEMTIME* local) {
    return zone ? original_SystemTimeToTzSpecificLocalTime(zone, utc, local) : utc_to_local_ex(nullptr, utc, local);
}
BOOL WINAPI local_to_utc(const TIME_ZONE_INFORMATION* zone, const SYSTEMTIME* local, SYSTEMTIME* utc) {
    return zone ? original_TzSpecificLocalTimeToSystemTime(zone, local, utc) : local_to_utc_ex(nullptr, local, utc);
}
void WINAPI local_time(SYSTEMTIME* local) {
    SYSTEMTIME utc;
    GetSystemTime(&utc);
    utc_to_local_ex(nullptr, &utc, local);
}
DWORD WINAPI zone_info(TIME_ZONE_INFORMATION* result) {
    SYSTEMTIME utc{}, local{};
    GetSystemTime(&utc);
    if (!utc_to_local_ex(nullptr, &utc, &local) ||
        !GetTimeZoneInformationForYear(local.wYear, &profile.zone, result)) return TIME_ZONE_ID_INVALID;
    if (!result->DaylightDate.wMonth) return TIME_ZONE_ID_UNKNOWN;
    FILETIME u{}, l{};
    SystemTimeToFileTime(&utc, &u);
    SystemTimeToFileTime(&local, &l);
    ULARGE_INTEGER utc_ticks{}, local_ticks{};
    utc_ticks.LowPart = u.dwLowDateTime; utc_ticks.HighPart = u.dwHighDateTime;
    local_ticks.LowPart = l.dwLowDateTime; local_ticks.HighPart = l.dwHighDateTime;
    auto bias = (static_cast<LONGLONG>(utc_ticks.QuadPart) - static_cast<LONGLONG>(local_ticks.QuadPart)) / 600000000;
    return bias == result->Bias + result->DaylightBias ? TIME_ZONE_ID_DAYLIGHT : TIME_ZONE_ID_STANDARD;
}
DWORD WINAPI dynamic_zone(DYNAMIC_TIME_ZONE_INFORMATION* result) {
    *result = profile.zone;
    TIME_ZONE_INFORMATION yearly;
    return zone_info(&yearly);
}

bool configure() {
    wchar_t name[80];
    object_name(name, GetCurrentProcessId(), L"profile");
    HANDLE mapping = OpenFileMappingW(FILE_MAP_READ, FALSE, name);
    if (!mapping) return false;
    auto view = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, sizeof(profile));
    if (view) {
        memcpy(&profile, view, sizeof(profile));
        UnmapViewOfFile(view);
    }
    CloseHandle(mapping);
    if (!view) return false;
    if (profile.region[0]) region_id = LocaleNameToLCID(profile.region, 0);
    if (profile.language[0]) {
        ui_id = LANGIDFROMLCID(LocaleNameToLCID(profile.language, 0));
        // The fixed-size, zero-filled language buffer is a double-terminated MUI list.
        ULONG count = 0;
        if (!SetProcessPreferredUILanguages(MUI_LANGUAGE_NAME, profile.language, &count) ||
            !SetThreadPreferredUILanguages(MUI_LANGUAGE_NAME, profile.language, &count)) return false;
    }
    if (DetourTransactionBegin() != NO_ERROR) return false;
    LONG error = DetourUpdateThread(GetCurrentThread());
#define ATTACH(api, replacement) \
    if (!error) error = DetourAttach(reinterpret_cast<PVOID*>(&original_##api), replacement)
    if (profile.page) {
        ATTACH(GetACP, page); ATTACH(GetOEMCP, page);
        ATTACH(MultiByteToWideChar, decode); ATTACH(WideCharToMultiByte, encode);
        ATTACH(GetCPInfo, cp_info); ATTACH(GetCPInfoExW, cp_info_ex);
        ATTACH(IsDBCSLeadByteEx, lead_ex); ATTACH(IsDBCSLeadByte, lead);
        ATTACH(CreateFileA, create_file); ATTACH(GetFileAttributesA, attributes);
        ATTACH(MessageBoxA, message); ATTACH(SetWindowTextA, set_text);
        ATTACH(TextOutA, text_out); ATTACH(GetTextExtentPoint32A, text_extent);
    }
    if (region_id) {
        ATTACH(GetUserDefaultLCID, region); ATTACH(GetSystemDefaultLCID, region);
        ATTACH(GetThreadLocale, region); ATTACH(GetUserDefaultLangID, region_language);
        ATTACH(GetSystemDefaultLangID, region_language); ATTACH(GetUserDefaultLocaleName, region_name);
        ATTACH(GetSystemDefaultLocaleName, region_name); ATTACH(GetLocaleInfoW, locale_info);
        ATTACH(GetLocaleInfoEx, locale_info_ex);
        ATTACH(GetDateFormatEx, date_format); ATTACH(GetTimeFormatEx, time_format);
        ATTACH(GetNumberFormatEx, number_format);
    }
    if (ui_id) {
        ATTACH(GetUserDefaultUILanguage, language); ATTACH(GetSystemDefaultUILanguage, language);
        ATTACH(GetUserPreferredUILanguages, preferred_languages);
        ATTACH(GetSystemPreferredUILanguages, preferred_languages);
    }
    if (profile.zone.TimeZoneKeyName[0]) {
        ATTACH(GetTimeZoneInformation, zone_info); ATTACH(GetDynamicTimeZoneInformation, dynamic_zone);
        ATTACH(GetLocalTime, local_time); ATTACH(SystemTimeToTzSpecificLocalTime, utc_to_local);
        ATTACH(TzSpecificLocalTimeToSystemTime, local_to_utc);
        ATTACH(SystemTimeToTzSpecificLocalTimeEx, utc_to_local_ex);
        ATTACH(TzSpecificLocalTimeToSystemTimeEx, local_to_utc_ex);
    }
    if (error) { DetourTransactionAbort(); return false; }
    if (DetourTransactionCommit() != NO_ERROR) return false;
    object_name(name, GetCurrentProcessId(), L"ready");
    HANDLE ready = OpenEventW(EVENT_MODIFY_STATE, FALSE, name);
    if (!ready) return false;
    BOOL signaled = SetEvent(ready);
    CloseHandle(ready);
    return signaled != FALSE;
}
} // namespace

// Detours requires an ordinal-one import in the provider.
extern "C" void LocaleProviderEntry() {}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(module);
    DetourRestoreAfterWith();
    return configure();
}
