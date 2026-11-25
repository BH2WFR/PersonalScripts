# Locale Launcher

Run `conda run -n base python run-script.py locale-launcher` on Windows 10 or later.
The left column controls one launch. The right column shows Windows regional settings, UI language, ANSI/OEM code pages and the active time zone. User and system defaults appear separately when they differ. The UTF-8 code page is 65001.

The launcher accepts a single Windows executable (`.exe` or `.com`) from Explorer, the file picker, or the clipboard (including a quoted path). **Run** inherits the launcher's privileges. **Run as administrator** uses the Windows UAC verb.

**Start in** is prefilled with the working directory from which Locale Launcher started. Both launch buttons use that directory when the field is empty. Enter a path or use **Open folder…** to choose a different directory. Relative paths are resolved from the original startup directory.

The optional **Arguments** field passes its text to the target as a Windows command-line tail. For example, `--input "C:\My Files\日本語.txt" ""` includes a quoted path and an empty argument. Both launch buttons preserve the text.

Double-click [`_locale-info.com`](../_locale-info.com) to view the host defaults, or open it in Locale Launcher to inspect the effective settings for that launch. Its dialog shows the user and system regions, ANSI/OEM code pages, UI languages, time zone, local time, actual process elevation, working directory and received argument text.

## Compatibility

When every selection is **Unchanged (use host)**, Windows starts the target directly. For overrides the launcher selects the included x86 or x64 runtime by the target's PE machine type. Each override applies to the selected process for its lifetime. Programs that hand off to another executable need that executable selected directly.

The runtime handles common Win32 regional queries and formatting, ANSI/OEM code page queries and default conversions, several ANSI file and text APIs, MUI resource preferences, and local time conversions using Windows time zone rules. Applications with explicit encodings, bundled language settings, custom rendering, or direct registry queries can behave differently. The application needs resources in the chosen UI language. Managed AnyCPU programs and native ARM64 targets are outside the override runtime's scope.

## Rebuild the included runtime

The two architecture directories under `bin` contain the fixed-purpose launcher and its locale provider. They statically link Microsoft Detours v4.0.1, commit `e4bfd6b03e50de46b47abfbd1e46b384f0c5f833`. The third-party license is distributed with the runtime. [Detours source](https://github.com/microsoft/Detours/tree/v4.0.1) · [License](bin/Detours-LICENSE.md)

From the repository root, use an MSVC Developer PowerShell for the target architecture, a Windows SDK, CMake, Ninja and a Detours v4.0.1 checkout. Set `$arch` to match that shell (`x86` or `x64`) and `$detours` to the absolute checkout path.

```powershell
$source = 'tools/windows/locale_launcher'
$build = "tmp/locale-launcher-build-$arch"
cmake -S "$source/native" -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release "-DDETOURS_SOURCE=$detours"
cmake --build $build
cmake --install $build --prefix "$source/bin/$arch"
if ($arch -eq 'x86') { Copy-Item -LiteralPath "$build/_locale-info.com" -Destination 'tools/windows/_locale-info.com' }
conda run -n base python -m unittest discover -s test -p test_locale_launcher.py
```

Repeat in the other architecture's Developer PowerShell. The native test builds a multilingual executable, reads its effective settings and checks resource selection. The GUI test also checks file drops, pasted files and paths, the file picker and both launch actions.
