# Tk text input

`utils.tk_input` exports `TkTextInput` through `utils`. Importing either module
does not load Tkinter or Windows DLLs.

```python
text = tkinter.Text(root, undo=True)
text_input = TkTextInput(text)
```

Construct on the GUI thread and retain the object until the widget is destroyed.
On Windows with Tk 8, it installs a callback on the widget's toplevel window.
Completed IME compositions containing non-BMP characters are decoded as UTF-16
and queued intact for the focused Text widget. Tk's text insertion binding
handles selection replacement, undo and scrolling. BMP-only input, in-progress
composition and other focused widgets continue through Tk's native handler.
macOS, Linux and Tk 9 need no callback. No third-party dependency is added.

This works around Tk 8.6.14's `HandleIMEComposition` stopping at the first high
surrogate, discarding the remainder of the composition. It does not alter fonts,
clipboard operations, keyboard layouts, system IME settings or global hooks.
It does not replace Tk's other keyboard-input or text-navigation code.

The callback is removed when the Text widget or toplevel is destroyed;
`close() -> None` also removes it and is safe to repeat. Construction raises
`OSError` if installation fails. IME read failures fall back to native handling;
unexpected callback errors are reported through Tk's callback exception handler.
Install once per Text widget; other controls need their own insertion semantics.

Upstream: https://github.com/tcltk/tk/blob/core-8-6-14/win/tkWinX.c
