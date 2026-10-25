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
`context.build_hosts` and `context.projects` expose immutable snapshots for
plugins that bind their own named configuration to existing build profiles.
Use `run_host`, `capture_host`, `build_host_command`, and `board_command`
instead of constructing application-internal jobs.

`context.config` contains persistent plugin configuration. For transient data
shared by a plugin's views and handlers, use `context.runtime_state`. The host
keeps that dictionary for the lifetime of the client process and never writes
it to the plugin YAML configuration.

Actions may declare an `availability` callback. It returns `(enabled, reason)`
and lets the host gray out an action while showing a concrete disabled reason.

Plugins with persistent entities may export `config_contributor()`. It returns
the same `ConfigContributor` contract used by built-in components and declares
entity adapters, GUID references, and deletion policies. Contributors are
loaded for every plugin with persisted state, including disabled plugins, so
disabling a UI extension does not hide its references from configuration
integrity checks. The shared `ConfigStore` builds deletion warnings and invokes
dependent detach handlers only after the user confirms the target deletion.

Plugins that need to upgrade persisted data may also export
`migrate_config(config)`. The host calls it once in the configuration load
pipeline, before `ConfigStore` is initialized, and saves the configuration when
the function returns `True`. The callback receives the complete application
configuration so it can migrate references to host-owned GUIDs. Views,
previews, handlers, and `config_contributor()` must treat loaded configuration
as current-schema data and must not perform compatibility migration.

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

For inline field editing, keep the current value and cursor in the view and
pass input events to `context.inline_edit(event, value, cursor)`. The returned
action is `edit`, `save`, `cancel`, or `noop`. During rendering, use
`ui.cursor(row, column)` and the `editing` style so cursor visibility and field
appearance stay consistent with host configuration screens.
