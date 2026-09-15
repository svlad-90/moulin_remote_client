# Preflight UI Component

Owns parsing and formatting of build-host preflight command output for display.
It intentionally does not own curses attributes or rendering; the application
maps the returned text and part status to colors.
