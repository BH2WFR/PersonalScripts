"""Optional offline MathJax 2 preview for transcribed document text and formulas."""

from functools import lru_cache
from html import escape
import json
from pathlib import Path
import sys
import sysconfig
from typing import TYPE_CHECKING, Any

from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from markdown_it.rules_inline import StateInline
    from markdown_it.rules_block import StateBlock
    from markdown_it.token import Token

from PySide6 import QtCore, QtGui, QtWidgets, __version__ as pyside_version
from utils.qt_styles import set_text_style
from ..common.viewer import MAX_SCALE, MIN_SCALE, ZOOM_STEP, install_preview_menu


@lru_cache(maxsize=1)
def _markdown_parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    parser.disable(["link", "image", "autolink"])
    parser.inline.ruler.before("escape", "tex", _inline_math)
    parser.block.ruler.before("paragraph", "display_tex", _display_block,
                              {"alt": ["paragraph", "reference", "blockquote", "list"]})
    parser.add_render_rule("tex", _render_math)
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


def _render_math(_renderer: object, tokens: list["Token"], index: int, options: Any, env: Any) -> str:
    token = tokens[index]
    opening = r"\[" if token.markup in ("$$", r"\[") else r"\("
    return f"<{token.tag}>{opening}{escape(token.content)}{_MATH_END[opening]}</{token.tag}>"


def markdown_html(text: str) -> str:
    """Render Markdown while keeping TeX intact and treating input HTML as text."""
    return _markdown_parser().render(text)


def preview_resources() -> tuple[Path | None, str]:
    """Locate the offline renderer and report the missing components for this interpreter."""
    problems = []
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except (ImportError, OSError) as exc:
        problems.append(f"Qt WebEngine could not load ({exc}). In the Python environment shown below, run:\n"
                        f'python -m pip install "PySide6-Addons=={pyside_version}"')
    packages = Path(sysconfig.get_path("purelib"))
    prefix = Path(sys.prefix)
    target = prefix / "share/mathjax"
    # In the active Conda environment: conda install "conda-forge::mathjax=2.7.7"
    # The package installs under Library/lib on Windows and lib on Unix.
    conda_assets = prefix / ("Library/lib" if sys.platform == "win32" else "lib") / "mathjax"
    for root in (packages / "nbclassic/static/components/MathJax",
                 packages / "spyder/plugins/help/utils/js/mathjax", target, conda_assets):
        if all((root / name).is_file() for name in ("MathJax.js", "config/TeX-AMS_SVG-full.js", "extensions/Safe.js")):
            break
    else:
        problems.append('Install MathJax in the active Conda environment:\nconda install "conda-forge::mathjax=2.7.7"\n'
                        f"For manual setup, extract MathJax 2.7.9 so its MathJax.js is at {target / 'MathJax.js'}.")
    if problems:
        return None, "\n\n".join([*problems, f"Python: {sys.executable}\nRestart the tool after installation."])
    return root, ""


class FormulaPreview(QtWidgets.QWidget):
    """Create an offline web view on first use and render the latest transcription."""

    imageReady = QtCore.Signal(QtGui.QImage, bool)
    exportFailed = QtCore.Signal(str)
    MAX_EXPORT_PIXELS = 48_000_000

    def __init__(self, root: Path | None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = root.resolve() if root is not None else None
        self.layout_box = QtWidgets.QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.value = ""
        self.fragment = False
        self.ready = False
        self.browser = None
        self.revision = 0
        self.exporting = False
        self.copy_image = QtGui.QAction("Copy image", self)
        self.save_image = QtGui.QAction("Save image...", self)
        self.copy_image.triggered.connect(lambda: self._export_image(False))
        self.save_image.triggered.connect(lambda: self._export_image(True))
        self.setToolTip("Wheel to zoom, drag to pan. Shift-drag to select text.")

    def reset_view(self) -> None:
        """Start each recognition run at the rendered document's natural size."""
        if self.ready and self.browser is not None:
            self.browser.page().runJavaScript("resetView()")

    def _original_size(self) -> None:
        if self.ready and self.browser is not None:
            self.browser.page().runJavaScript("zoomAt(1, innerWidth / 2, innerHeight / 2)")

    def _fit_view(self) -> None:
        if self.ready and self.browser is not None:
            self.browser.page().runJavaScript("fitView()")

    def display(self, text: str, *, fragment: bool = False) -> None:
        if self.root is None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
        from PySide6.QtWebEngineWidgets import QWebEngineView
        if self.browser is not None and self.value == text and self.fragment == fragment:
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
            install_preview_menu(self.browser, reset=self.reset_view, fit=self._fit_view, original=self._original_size)
            self.browser.addActions([self.copy_image, self.save_image])
            self.browser.addAction(page.action(QWebEnginePage.WebAction.Copy))
            self.layout_box.addWidget(self.browser)
            self.browser.loadFinished.connect(self._loaded)
            self.browser.setHtml(r"""<!doctype html><meta charset="utf-8">
<style>html{min-height:100%;cursor:grab;overflow-anchor:none}html.dragging{cursor:grabbing;user-select:none}
html.fitted{overflow:hidden}
@media print {
    html,html.fitted{min-height:0;overflow:visible}
    #sheet{transform:none !important}
    *{-webkit-print-color-adjust:exact}
}
body{font:16px sans-serif;margin:0}#sheet{transform-origin:0 0;padding:1em}#output{overflow-wrap:anywhere}
#output:empty::before{content:"Run recognition to preview Markdown and formulas.";color:#666}
#output .noError,#output .MathJax_Error,#output .renderer-error{color:#b00020}
table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:.3em}pre{white-space:pre-wrap}</style>
<script type="text/x-mathjax-config">
MathJax.Hub.Config({showMathMenu:false,messageStyle:"none",extensions:["Safe.js"],
 TeX:{extensions:["color.js","boldsymbol.js"],noUndefined:{disabled:true}},
 Safe:{allow:{URLs:"none",classes:"none",styles:"none",cssIDs:"none"}},
 tex2jax:{inlineMath:[["$","$"],["\\(","\\)"]],processEscapes:true}});
// OCR can place a printed row number inside aligned, where AMS forbids \tag.
// Use align* for that display in MathJax so only explicitly tagged rows get numbers.
MathJax.Hub.Register.StartupHook("TeX Jax Ready", function () {
    MathJax.InputJax.TeX.prefilterHooks.Add(function (data) {
        if (!data.display) return;
        const block = /^\s*\\begin\{aligned\}([\s\S]*)\\end\{aligned\}\s*$/.exec(data.math);
        if (!block || /^\s*\[[tbc]\]/.test(block[1]) || /\\(?:begin|end)\{aligned\}/.test(block[1])) return;
        if (/\\tag\*?\s*\{[^{}]*\}\s*(?:\\\\|$)/.test(block[1])) {
            data.math = '\\begin{align*}' + block[1] + '\\end{align*}';
        }
    });
});
</script><script src="MathJax.js?config=TeX-AMS_SVG-full"></script>
<div id="sheet"><div id="output"></div></div>
<script>
const sheet = document.getElementById('sheet');
const [minScale, maxScale, zoomStep] = ZOOM_SETTINGS;
let scale = 1, offsetX = 0, offsetY = 0;
const viewport = document.documentElement;
function positionSheet() {
    sheet.style.transform = 'translate(' + offsetX + 'px,' + offsetY + 'px) scale(' + scale + ')';
}
function resetView() {
    viewport.classList.remove('fitted');
    scale = 1;
    offsetX = offsetY = 0;
    positionSheet();
    window.scrollTo(0, 0);
}
function fitView() {
    resetView();
    viewport.classList.add('fitted');
    const output = document.getElementById('output');
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    function include(rect) {
        if (!rect.width || !rect.height) return;
        left = Math.min(left, rect.left);
        top = Math.min(top, rect.top);
        right = Math.max(right, rect.right);
        bottom = Math.max(bottom, rect.bottom);
    }
    // Blocks can span the page even if a centered equation uses only a few pixels.
    output.querySelectorAll('svg,table,hr').forEach(el => include(el.getBoundingClientRect()));
    const walker = document.createTreeWalker(output, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.textContent.trim() || node.parentElement.closest('svg,script,style')) continue;
        range.selectNodeContents(node);
        include(range.getBoundingClientRect());
    }
    if (!Number.isFinite(left) || innerWidth <= 16 || innerHeight <= 16) return;
    scale = Math.min(maxScale, (innerWidth - 16) / (right - left), (innerHeight - 16) / (bottom - top));
    offsetX = (innerWidth - scale * (right + left)) / 2;
    offsetY = (innerHeight - scale * (bottom + top)) / 2;
    positionSheet();
}
function refitIfNeeded() {
    if (viewport.classList.contains('fitted')) fitView();
}
function renderOutput(html, revision) {
    const output = document.getElementById('output');
    if (!window.MathJax || !MathJax.Hub) {
        const error = document.createElement('p');
        error.className = 'renderer-error';
        error.textContent = 'Formula preview failed to load MathJax.';
        output.innerHTML = html;
        output.prepend(error);
        sheet.dataset.rendered = revision;
        return;
    }
    MathJax.Hub.Queue(function () {
        MathJax.Hub.getAllJax(output).forEach(jax => jax.Remove());
        output.innerHTML = html;
    }, ['Typeset', MathJax.Hub, output], function () {
        sheet.dataset.rendered = revision;
        refitIfNeeded();
    });
}
window.addEventListener('resize', refitIfNeeded);
function zoomAt(next, x, y) {
    viewport.classList.remove('fitted');
    const rect = sheet.getBoundingClientRect();
    offsetX += (x - rect.left) * (1 - next / scale);
    offsetY += (y - rect.top) * (1 - next / scale);
    scale = next;
    positionSheet();
}
window.addEventListener('wheel', event => {
    if (!event.deltaY) return;
    event.preventDefault();
    const steps = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? event.deltaY / 3 :
                  event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? event.deltaY : event.deltaY / 100;
    const next = Math.max(minScale, Math.min(maxScale, scale * zoomStep ** -steps));
    zoomAt(next, event.clientX, event.clientY);
}, {passive: false});
let drag = null;
viewport.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.shiftKey || !event.isPrimary) return;
    event.target.setPointerCapture(event.pointerId);
    drag = {id: event.pointerId, x: event.clientX - offsetX, y: event.clientY - offsetY};
    viewport.classList.add('dragging');
});
viewport.addEventListener('pointermove', event => {
    if (!drag || drag.id !== event.pointerId) return;
    viewport.classList.remove('fitted');
    offsetX = event.clientX - drag.x;
    offsetY = event.clientY - drag.y;
    positionSheet();
});
viewport.addEventListener('lostpointercapture', () => {
    drag = null;
    viewport.classList.remove('dragging');
});
resetView();
</script>""".replace("ZOOM_SETTINGS", json.dumps((MIN_SCALE, MAX_SCALE, ZOOM_STEP))),
                                 QtCore.QUrl.fromLocalFile(str(root / "index.html")))
        self.value, self.fragment = text, fragment
        self.revision += 1
        self._sync_export_actions()
        if self.ready:
            self._update()

    def _loaded(self, ok: bool) -> None:
        self.ready = ok
        self._sync_export_actions()
        if ok:
            self._update()

    def _update(self) -> None:
        if self.browser is not None:
            html = (f'<div style="white-space:pre-wrap">{escape(self.value)}</div>'
                    if self.fragment and self.value else markdown_html(self.value))
            self.browser.page().runJavaScript(f"renderOutput({json.dumps(html)}, {self.revision})")

    def _sync_export_actions(self) -> None:
        enabled = self.ready and bool(self.value.strip()) and not self.exporting
        self.copy_image.setEnabled(enabled)
        self.save_image.setEnabled(enabled)

    def _export_image(self, save: bool) -> None:
        """Print the typeset content at natural scale, including off-screen pixels."""
        if self.browser is None or not self.copy_image.isEnabled():
            return
        revision = self.revision
        self.exporting = True
        self._sync_export_actions()

        def finish() -> None:
            self.exporting = False
            self._sync_export_actions()

        def printed(data: QtCore.QByteArray) -> None:
            finish()
            if revision != self.revision:
                return
            try:
                image = self._rasterize_pdf(bytes(data.data()))
            except (ValueError, RuntimeError, MemoryError) as exc:
                self.exportFailed.emit(str(exc) or "Could not render the preview image.")
                return
            self.imageReady.emit(image, save)

        def measured(dimensions: str) -> None:
            if revision != self.revision or self.browser is None:
                finish()
                return
            if not dimensions:
                finish()
                self.exportFailed.emit("Wait for formula rendering to finish and try again.")
                return
            width, height = json.loads(dimensions)
            if width * height > self.MAX_EXPORT_PIXELS:
                finish()
                self.exportFailed.emit("The formula preview is too large to export as one image.")
                return
            # CSS uses 96 pixels/inch and PDF uses 72 points/inch.
            size = QtGui.QPageSize(QtCore.QSizeF(width * .75, height * .75), QtGui.QPageSize.Unit.Point,
                                   "Preview", QtGui.QPageSize.SizeMatchPolicy.ExactMatch)
            layout = QtGui.QPageLayout(size, QtGui.QPageLayout.Orientation.Portrait, QtCore.QMarginsF())
            self.browser.page().printToPdf(printed, layout)

        self.browser.page().runJavaScript(
            f"Number(sheet.dataset.rendered) === {revision} ? "
            "JSON.stringify([sheet.scrollWidth + 2, sheet.scrollHeight + 2]) : ''", 0, measured)

    @classmethod
    def _rasterize_pdf(cls, data: bytes) -> QtGui.QImage:
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as document:
            scale = pymupdf.Matrix(96 / 72, 96 / 72)
            sizes = [(page.rect * scale).irect for page in document]
            width, height = max(size.width for size in sizes), sum(size.height for size in sizes)
            if width * height > cls.MAX_EXPORT_PIXELS:
                raise ValueError("The formula preview is too large to export as one image.")
            image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB32)
            if image.isNull():
                raise MemoryError("Insufficient memory to export the formula preview.")
            image.fill(QtCore.Qt.GlobalColor.white)
            painter = QtGui.QPainter(image)
            try:
                y = 0
                for page in document:
                    pix = page.get_pixmap(matrix=scale)
                    tile = QtGui.QImage(pix.samples_mv, pix.width, pix.height, pix.stride,
                                        QtGui.QImage.Format.Format_RGB888)
                    painter.drawImage(0, y, tile)
                    y += pix.height
            finally:
                painter.end()
            return image


class FormulaPreviewTab(FormulaPreview):
    """Show the optional renderer or its installation hint in the same tab."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        root, hint = preview_resources()
        super().__init__(root, parent)
        if root is None:
            self.setToolTip("")
            label = QtWidgets.QLabel(hint)
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            set_text_style(label, "red")
            self.layout_box.addWidget(label)
