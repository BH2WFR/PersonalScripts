"""Regression coverage for the Rime conversion ports and interactive entries."""

from collections.abc import Iterator
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.rime import Rime, RimeEntry, RimeFormat


ROOT = Path(__file__).resolve().parents[1]


def load_entry(name: str) -> ModuleType:
    """Import a kebab-case entry without running its interactive main."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "IME" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


aux = load_entry("rime-aux-code-generator")
userdict = load_entry("rime-userdict-to-dict")


class RimeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def source(self, text: str, name: str = "source.txt") -> Path:
        """Create an isolated UTF-8 fixture."""
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, name: str, answers: list[str], *args: str) -> subprocess.CompletedProcess[str]:
        """Exercise actual stdin and entry-boundary behavior."""
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "IME" / f"{name}.py"), *args],
            input="\n".join(answers) + "\n", text=True, encoding="utf-8",
            capture_output=True, timeout=30,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )

    def test_shape_bom_header_columns_and_malformed_rows(self) -> None:
        source = self.source(
            '\ufeff# Rime dictionary\n---\nname: test\ncolumns: [code, weight, text]\n...\n'
            '# comment\na\t100%\t日\nabc\tbad-weight\t明\ninvalid\n\t5\t月\n'
        )
        result = Rime.read(source, format=RimeFormat.DICT, read_weights=False)
        self.assertEqual(result.entries, [RimeEntry("日", "a"), RimeEntry("明", "abc")])
        self.assertEqual(result.invalid_rows, 2)
        self.assertEqual(result.invalid_lines, [9, 10])

    def test_aux_modes_single_code_choices_and_original_order(self) -> None:
        entries = [RimeEntry("月", "b"), RimeEntry("明", "abc"), RimeEntry("日", "a")]
        self.assertEqual(aux.generate_aux_rows(entries), ["日=a", "明=a", "月=b"])
        for single, expected in [
            (aux.SingleCodeMode.KEEP, ["日=a", "明=ac", "月=b"]),
            (aux.SingleCodeMode.REPEAT, ["日=aa", "明=ac", "月=bb"]),
            (aux.SingleCodeMode.PREFIX, ["日=qa", "明=ac", "月=qb"]),
        ]:
            with self.subTest(single=single):
                self.assertEqual(aux.generate_aux_rows(
                    entries, mode=aux.AuxMode.FIRST_LAST, single=single, prefix="q",
                ), expected)

    def test_aux_filters_unicode_and_distinct_codes(self) -> None:
        entries = [
            RimeEntry("𠀀", "ab"), RimeEntry("𠀀", "ac"), RimeEntry("𠀀", "cd"),
            RimeEntry("日", "xa"), RimeEntry("日月", "ab"), RimeEntry("明", "a b"),
        ]
        self.assertEqual(aux.generate_aux_rows(entries, excluded_prefixes=("x",)), ["𠀀=a", "𠀀=c"])
        self.assertEqual(aux.generate_aux_rows(entries, allowed_texts={"日"}), ["日=x"])
        self.assertEqual(aux.generate_aux_rows(entries, allowed_texts=set()), [])
        self.assertIn("日月=a", aux.generate_aux_rows(entries, single_char_only=False))

    def test_snapshot_detection_counts_and_weight_conversion(self) -> None:
        source = self.source(
            '# Rime user dictionary\n#@/db_name\ttest\n'
            'ni hao \t你好\tc=7 d=0.2 t=10\n'
            'shan chu \t删除\tc=-2 d=1 t=10\n'
            'ling \t零\tc=0 d=0 t=0\n'
            'ni hao \t你好\tc=99 d=0 t=0\n'
            'huai \t坏\tc=3oops d=0\n'
        )
        result = Rime.read(source)
        self.assertEqual(result.invalid_rows, 1)
        self.assertEqual(userdict.convert_entries(result.entries, factor=0.5), [
            RimeEntry("零", "ling"), RimeEntry("你好", "ni hao", 3),
        ])
        self.assertEqual(userdict.convert_entries(result.entries, use_weights=False), [
            RimeEntry("零", "ling"), RimeEntry("你好", "ni hao"),
        ])
        self.assertEqual(Rime.read(self.source('a \t日\tc=4 d=0\n')).entries, [RimeEntry("日", "a", 4)])

    def test_export_and_generated_dictionary_roundtrip(self) -> None:
        source = self.source('# Rime user dictionary export\n你好\tni hao\t9\n零\tling\n')
        entries = userdict.convert_entries(Rime.read(source).entries)
        output = self.directory / "custom.dict.yaml"
        Rime.write_rows(output, userdict.dictionary_rows(entries, "true"), sources=[source])
        self.assertEqual(Rime.read(output).entries, entries)
        self.assertIn('name: "true"', output.read_text(encoding="utf-8"))
        self.assertNotIn(b"\r", output.read_bytes())
        self.assertFalse(output.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_invalid_headers_binary_and_utf8_fail(self) -> None:
        for content in (
            '---\nname: test\n', '---\ncolumns: [text]\n...\n',
            '---\ncolumns: [text, code, code]\n...\n',
            '---\nname: [\n...\n', '---\n- wrong\n...\n', 'binary\0file',
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                Rime.read(self.source(content))
        source = self.directory / "bad-encoding.txt"
        source.write_bytes(b"\xff\xfe\x81")
        with self.assertRaises(UnicodeError):
            Rime.read(source)

    def test_invalid_options(self) -> None:
        for factor in (-1, float("nan"), float("inf")):
            with self.subTest(factor=factor), self.assertRaises(ValueError):
                userdict.convert_entries([], factor=factor)
        with self.assertRaises(ValueError):
            aux.generate_aux_rows([], single=aux.SingleCodeMode.PREFIX, prefix="xx")
        with self.assertRaises(ValueError):
            userdict.dictionary_rows([], "bad\nname")

    def test_writer_protects_sources_and_existing_output_on_failure(self) -> None:
        source = self.source("original")
        with self.assertRaises(ValueError):
            Rime.write_rows(source, ["replacement"], sources=[source], overwrite=True)
        alias = self.directory / "hardlink.txt"
        os.link(source, alias)
        with self.assertRaises(ValueError):
            Rime.write_rows(alias, ["replacement"], sources=[source], overwrite=True)
        with self.assertRaises(FileExistsError):
            Rime.write_rows(source, ["replacement"])

        def broken_rows() -> Iterator[str]:
            yield "partial"
            raise OSError("simulated write failure")

        with self.assertRaises(OSError):
            Rime.write_rows(source, broken_rows(), overwrite=True)
        self.assertEqual(source.read_text(encoding="utf-8"), "original")
        self.assertFalse(list(self.directory.glob("*.tmp")))

    def test_interactive_aux_prefix(self) -> None:
        source = self.source('日\ta\n明\tabc\n𠀀\tbc\n')
        output = self.directory / "aux.txt"
        result = self.run_cli("rime-aux-code-generator", [
            str(source), "2", "3", "x", "1", "", "N", str(output),
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "日=xa\n明=ac\n𠀀=bc\n")

    def test_interactive_userdict_and_deletion_without_weights(self) -> None:
        source = self.source('a \t日\tc=5 d=0\nb \t月\tc=-1 d=0\n')
        output = self.directory / "custom.dict.yaml"
        result = self.run_cli("rime-userdict-to-dict", [
            str(source), "1", "2", str(output), "custom",
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(Rime.read(output).entries, [RimeEntry("日", "a")])

    def test_cli_help_and_empty_results(self) -> None:
        source = self.source('# comments only\n')
        for name, answers in (
            ("rime-aux-code-generator", [str(source), "1", "1", "", "N"]),
            ("rime-userdict-to-dict", [str(source), "1", "2"]),
        ):
            with self.subTest(name=name):
                help_result = self.run_cli(name, [], "--help")
                self.assertEqual(help_result.returncode, 0, help_result.stderr)
                self.assertIn("Requirements:", help_result.stdout)
                result = self.run_cli(name, answers)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("no output written", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
