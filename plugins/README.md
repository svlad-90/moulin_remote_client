# Plugins

Moulin Remote Client discovers plugins from immediate subdirectories containing
`plugin.yaml`. Discovered plugins are enabled and configured from the main
**Settings** screen.

Minimal layout:

```text
plugins/
  board_diagnostics/
    plugin.yaml
    plugin.py
```

Minimal `plugin.yaml`:

```yaml
api_version: 1
id: board-diagnostics
name: Board diagnostics
entrypoint: plugin.py

settings:
  timeout:
    type: integer
    label: SSH timeout
    default: 10
    minimum: 1

tabs:
  - id: diagnostics
    label: Diagnostics
    actions:
      - id: check-all
        label: Check all boards
        description: Check every configured board host.
        handler: check_all_boards
        preview: check_preview
        job_slot: board
```

Handlers receive a `PluginContext` instead of the internal application object:

```python
def check_preview(context):
    return f"Configured boards: {len(context.boards)}"


def check_active_board(context):
    context.commands.run_board(
        context.active_board_id,
        "Check active board",
        ["uname -a"],
    )
```

`context.boards` contains snapshots of every configured board profile, not only
the active one. Use `context.commands.run_boards(title, commands_by_board)` to
run one logged sequential job across an explicit set of board IDs.

An action can open a custom host-managed view instead of calling a handler:

```yaml
views:
  - id: matrix
    label: Board matrix
    factory: create_matrix

tabs:
  - id: diagnostics
    label: Diagnostics
    actions:
      - id: matrix
        label: Open board matrix
        view: matrix
```

The factory returns an object with `render(ui, context)` and
`handle_event(event, context)` methods. Optional `on_enter(context)`,
`on_tick(context)`, and `on_leave(context)` methods receive lifecycle events.
The host owns curses input, refresh, resize, navigation, jobs, logs, and
dialogs. The view draws only through the supplied `PluginCanvas`.
