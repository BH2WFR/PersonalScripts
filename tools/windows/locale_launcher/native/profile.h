#pragma once
#include <windows.h>
#include <cwchar>

// These names exist only during the startup of one selected process.
inline void object_name(wchar_t (&name)[80], DWORD pid, const wchar_t* purpose) {
    swprintf_s(name, L"Local\\PersonalScripts.LocaleLauncher.%lu.%ls", pid, purpose);
}

struct Profile {
    wchar_t region[LOCALE_NAME_MAX_LENGTH]{};
    wchar_t language[LOCALE_NAME_MAX_LENGTH]{};
    UINT page{};
    DYNAMIC_TIME_ZONE_INFORMATION zone{};
};
