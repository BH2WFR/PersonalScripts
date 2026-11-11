# Shared utilities

`utils/__init__.py` re-exports the public classes and ANSI constants used by
project scripts through `from utils import *`. Implementations belong in their
canonical modules. Qt-only controls are imported explicitly from
`utils.qt_widgets`; ordinary utility imports do not load Qt, PyMuPDF, Pillow or
application packages.

Use this index to read only the reference needed for a task. References describe
the public calls and important ownership boundaries; module docstrings and
signatures provide implementation-level detail. When editing utils, update the
corresponding `docs/*.md` in the same change to reflect the affected API, behavior
and important internal reuse boundaries. Keep this index aligned with module
ownership and public exports.

## API reference

| Topic | Public interface | Canonical modules |
| --- | --- | --- |
| [Configuration](docs/config.md) | ConfigStore, ConfigBusyError, EncryptedValue | [config.py](config.py) |
| [Environment, system and paths](docs/runtime.md) | Environment, PythonEnvironment, RuntimeKind, System, LinuxGui, DiskInfo, DiskScan, Paths | [environment.py](environment.py), [system.py](system.py), [paths.py](paths.py) |
| [Console and interaction](docs/terminal.md) | Console, Input, RangeParity, Menu, MenuOption, Cursor, CmdCheck, ANSI constants | [console.py](console.py), [input.py](input.py), [menu.py](menu.py), [menu_option.py](menu_option.py), [cursor.py](cursor.py), [cmd_check.py](cmd_check.py), [ansi.py](ansi.py) |
| [PDF](docs/pdf.md) | Pdf, PdfBookmark | [pdf.py](pdf.py) |
| [LLM](docs/llm.md) | Llm, LlmSettings, LlmReasoning, LlmResponse, LlmProfile, LlmProfiles | [llm.py](llm.py); private [_llm_qt.py](_llm_qt.py) |
| [Fonts](docs/font.md) | Font, FontFace, FontStyle | [font.py](font.py) |
| [Keyboard](docs/keyboard.md) | Keyboard, WindowsScanCode, ScanCodePrefix | [keyboard.py](keyboard.py) |
| [Unicode text](docs/unicode_text.md) | UnicodeText, UnicodeCharacter, UnicodeReport, TextStatistics | [unicode_text.py](unicode_text.py) |
| [Tk text input](docs/tk_input.md) | TkTextInput | [tk_input.py](tk_input.py) |
| [Qt controls](docs/qt.md) | NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox, install_no_wheel_controls | [qt_widgets.py](qt_widgets.py) |

## Imports from category scripts

For entries directly inside `tools/<category>/`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402
```

Adjust the parent depth for other locations; a file directly inside `tmp/`
uses `parents[1]`. Private packages follow their entry's existing loader.

CLI entries keep authored help in a top-level `HELP` string. Use
`Console.argument_parser(HELP)` for argument parsing with that exact help text;
see the [terminal reference](docs/terminal.md).

## Maintenance

Reuse existing helpers before adding new ones. Shared behavior belongs in the
module responsible for it; application models, prompts and workflows remain in
their tool packages. Keep dependencies lazy where the feature is optional and
keep utilities independent of application imports. Private helpers are internal
composition points, not APIs for scripts.

Project-wide conventions and dependency placement are in
[AGENTS.md](../AGENTS.md). Test files live in [test/](../test/); run only the
relevant tests for the changed behavior.
