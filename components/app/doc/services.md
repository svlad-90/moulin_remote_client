# Application Services

`AppServicesController` is the application composition layer for the TUI
session. It wires menu, run-loop, action, job, dialog, config, sync, and
terminal-session controllers so `ClientApp` can remain a compatibility facade
and state holder instead of knowing how every component is constructed.

The controller delegates cohesive app-level scenarios to smaller controllers:

- `AppUiController` owns main TUI use cases: menu item construction, run loop,
  key handling, redraw, and selected action execution.
- `AppJobController` owns job lifecycle use cases and command/connection
  workflow access for the active TUI port.
- `AppWorkflowController` owns config, sync, terminal-session, and dialog
  workflows.

`AppServicesController` should stay a composition facade. New behavior should
land in the controller that owns the use case instead of becoming another
one-line helper on the facade.
