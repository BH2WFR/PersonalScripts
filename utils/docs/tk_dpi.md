# Tk DPI scaling

`TkDpi` is exported by `utils`; importing it does not load Tkinter or Windows DLLs.
It handles per-window font copies, layout spacing and Windows DPI notifications.

```python
System.enable_dpi_awareness()  # Before creating any Windows GUI window.
root = tkinter.Tk()
root.withdraw()
dpi = TkDpi(root)
root.geometry(f"{dpi.pixels(900)}x{dpi.pixels(600)}")
# Build controls with logical 96-DPI spacing and font=dpi.font().
dpi.track_spacing()
dpi.start(update_layout)  # update_layout(scale) sets styles, row/column sizes, etc.
root.deiconify()
root.mainloop()
```

Retain the controller for the window's lifetime and use it only on the GUI thread.
Construction runs idle geometry work to realize Tk's decorated native window;
withdraw before construction to avoid showing a partially built interface.

| API | Behavior |
| --- | --- |
| `TkDpi(root)` | Read the initial window DPI; accept a Tk root or Toplevel |
| `scale: float` | Current ratio relative to 96-DPI logical dimensions |
| `pixels(logical) -> int` | Round a logical dimension to current pixels |
| `font(name="TkDefaultFont") -> Font` | Cache an owned named-font copy, updated in place; never mutate other windows' fonts |
| `track_spacing()` | Before `start()`, capture existing widget padding, wrap lengths, borders, classic scrollbar widths and grid/pack padding as logical values |
| `start(on_change)` | Apply initial spacing/callback, then monitor changes; call once |
| `close()` | Detach native callback/cancel polling; safe to repeat, automatic on root destruction |

The callback updates application-specific dimensions: table row/column sizes,
minimum window size, ttk style padding, and image assets where applicable. Keep
styles local to the window, use the controller's fonts, and derive sizes from
logical values or the previous scale. Do not recreate widgets, clear selection,
reset user-adjusted column widths or run nested event loops. Character-count
dimensions such as Text height and Entry width are not pixel-scaled.

On Windows, `GetDpiForWindow` supplies the starting scale. `WM_DPICHANGED` is
handled on Tk's decorated outer window; fonts/layout update before applying the
suggested rectangle with `SetWindowPos`, without activation or z-order changes.
Mapping checks for a recreated native wrapper. `System.enable_dpi_awareness()`
is the shared startup initializer; declaring awareness alone does not resize Tk
widgets. Private `utils._win_subclass.WindowSubclass` owns native callback setup,
error forwarding and destruction, and is also used by `TkTextInput`.

On macOS, preserve Cocoa logical coordinates and native font/Retina rendering.
On X11/XWayland, use Tk's display scaling and observe changes every 500 ms. Tk 8
does not expose independent per-monitor logical DPI on X11; mixed-DPI behavior
there depends on the desktop/compositor. This is not a native Wayland backend.
Do not claim platform behavior verified without testing that environment.

`test/test_tk_dpi.py` sends native DPI messages at 100%, 150% and 200%, checks the
suggested window rectangle, fonts, row height, spacing and retained state, and
checks independent window fonts and cleanup. Also run the inspector and IME
tests when changing the shared callback infrastructure. A real mixed-DPI monitor
move remains a separate hardware check.

References:
- https://learn.microsoft.com/en-us/windows/win32/hidpi/wm-dpichanged
- https://www.tcl-lang.org/man/tcl8.6/TkCmd/tk.htm
