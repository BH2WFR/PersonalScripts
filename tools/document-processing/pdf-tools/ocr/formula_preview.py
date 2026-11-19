"""Optional offline MathJax 2 preview for transcribed document text and formulas."""

from importlib.util import find_spec
from functools import lru_cache
from html import escape
import json
from pathlib import Path
import sys
import sysconfig
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import StateInline
    from markdown_it.rules_block import StateBlock
    from markdown_it.token import Token

from PySide6 import QtCore, QtWidgets


@lru_cache(maxsize=1)
def _markdown_parser() -> "MarkdownIt":
    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    parser.disable(["link", "image", "autolink"])
    parser.inline.ruler.before("escape", "tex", _inline_math)
    parser.block.ruler.before("paragraph", "display_tex", _display_block,
                              {"alt": ["paragraph", "reference", "blockquote", "list"]})
    parser.renderer.rules["tex"] = _render_math
    return parser


_MATH_END = {r"\[": r"\]", "$$": "$$", r"\(": r"\)", "$": "$"}


def _inline_math(state: "StateInline", silent: bool) -> bool:
    """Capture delimited TeX before Markdown consumes escapes and emphasis."""
    start = state.pos
    for opening, closing in _MATH_END.items():
        if not state.src.startswith(opening, start):
            continue
        body = start + len(opening)
        end = state.src.find(closing, body, state.posMax)
        while end > body and state.src[end - 1] == "\\" and opening == "$":
            end = state.src.find(closing, end + 1, state.posMax)
        if end <= body or (opening == "$" and (state.src[body].isspace() or state.src[end-1].isspace())):
            return False
        if not silent:
            token = state.push("tex", "span", 0)
            token.markup, token.content = opening, state.src[body:end]
        state.pos = end + len(closing)
        return True
    return False


def _display_block(state: "StateBlock", start: int, stop: int, silent: bool) -> bool:
    """Keep multiline displays together, including those next to a paragraph."""
    opening = state.src[state.bMarks[start] + state.tShift[start]:state.eMarks[start]].strip()
    if opening not in ("$$", r"\["):
        return False
    for line in range(start + 1, stop):
        if state.src[state.bMarks[line] + state.tShift[line]:state.eMarks[line]].strip() == _MATH_END[opening]:
            if not silent:
                token = state.push("tex", "div", 0)
                token.markup = opening
                token.content = state.getLines(start + 1, line, state.blkIndent, False)
                token.map = [start, line + 1]
                state.line = line + 1
            return True
    return False


def _render_math(tokens: list["Token"], index: int, options: Any, env: Any) -> str:
    token = tokens[index]
    opening = r"\[" if token.markup in ("$$", r"\[") else r"\("
    return f"<{token.tag}>{opening}{escape(token.content)}{_MATH_END[opening]}</{token.tag}>"


def markdown_html(text: str) -> str:
    """Render Markdown while keeping TeX intact and treating input HTML as text."""
    try:
        return _markdown_parser().render(text)
    except ImportError:
        return "<div style='white-space:pre-wrap'>" + escape(text) + "</div>"


def mathjax_directory() -> Path | None:
    """Find an existing local MathJax distribution with the SVG renderer."""
    if find_spec("PySide6.QtWebEngineWidgets") is None:
        return None
    packages = Path(sysconfig.get_path("purelib"))
    for root in (packages / "nbclassic/static/components/MathJax",
                 packages / "spyder/plugins/help/utils/js/mathjax", Path(sys.prefix) / "share/mathjax"):
        if (root / "config/TeX-AMS_SVG-full.js").is_file() and (root / "extensions/Safe.js").is_file():
            return root
    return None


class FormulaPreview(QtWidgets.QWidget):
    """Create an offline web view on first use and render the latest transcription."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root.resolve()
        self.layout_box = QtWidgets.QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.value = ""
        self.ready = False
        self.browser = None

    def display(self, text: str) -> None:
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
        from PySide6.QtWebEngineWidgets import QWebEngineView
        if self.browser is not None and self.value == text:
            return
        if self.browser is None:
            root = self.root

            class LocalAssets(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    url = info.requestUrl()
                    if url.scheme() == "data":
                        return
                    if not url.isLocalFile() or not Path(url.toLocalFile()).resolve().is_relative_to(root):
                        info.block(True)

            # The view owns its page and must be destroyed before the profile.
            self.browser = QWebEngineView(self)
            self.profile = QWebEngineProfile(self)
            self.filter = LocalAssets(self.profile)
            self.profile.setUrlRequestInterceptor(self.filter)
            page = QWebEnginePage(self.profile, self.browser)
            self.browser.setPage(page)
            self.layout_box.addWidget(self.browser)
            self.browser.loadFinished.connect(self._loaded)
            self.browser.setHtml(r"""<!doctype html><meta charset="utf-8">
<style>body{font:16px sans-serif;margin:1em}#output{overflow-wrap:anywhere}
table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:.3em}pre{white-space:pre-wrap}</style>
<script type="text/x-mathjax-config">
MathJax.Hub.Config({showMathMenu:false,messageStyle:"none",extensions:["Safe.js"],
 TeX:{extensions:["color.js","boldsymbol.js"]},Safe:{allow:{URLs:"none",classes:"none",styles:"none",cssIDs:"none"}},
 tex2jax:{inlineMath:[["$","$"],["\\(","\\)"]],processEscapes:true}});
</script><script src="MathJax.js?config=TeX-AMS_SVG-full"></script>
<div id="output"></div>""", QtCore.QUrl.fromLocalFile(str(root / "index.html")))
        self.value = text
        if self.ready:
            self._update()

    def _loaded(self, ok: bool) -> None:
        self.ready = ok
        if ok:
            self._update()

    def _update(self) -> None:
        if self.browser is not None:
            self.browser.page().runJavaScript(
                "MathJax.Hub.Queue(function(){MathJax.Hub.getAllJax('output').forEach(j=>j.Remove());"
                "document.getElementById('output').innerHTML="
                + json.dumps(markdown_html(self.value)) + ";},['Typeset',MathJax.Hub,'output']);")
