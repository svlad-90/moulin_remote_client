# Main Menu

`main_menu` owns the top-level menu model for the TUI: setup actions, build
commands, board commands, sync actions, session actions, and status snapshots
needed to enable or disable menu rows.

The component exposes menu construction and state through
`components.main_menu.api`. It does not execute actions directly; action
execution stays in UI and workflow components.
