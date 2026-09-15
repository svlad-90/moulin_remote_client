# Terminal Port

`TerminalPortController` is the curses-backed UI adapter used by the TUI
controllers through `ClientApp`. It owns terminal input, safe drawing, color
attributes, simple framed drawing primitives, and suspend/restore operations.
