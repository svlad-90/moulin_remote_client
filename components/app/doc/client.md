# Client Facade

`ClientApp` is the TUI session facade used by the existing UI controllers. It is
bound to entrypoint dependencies through `client_app_class`, then delegates
session state, service composition, menu state, and terminal-port behavior to
the application components.

Terminal-port behavior is owned by `AppTerminalPortAdapter`. `ClientApp` keeps
the legacy port-shaped methods because existing screens call them directly, but
those methods should remain thin delegations to the adapter.
