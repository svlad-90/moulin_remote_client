# Host Configuration UI

`host_config_ui` owns interactive TUI workflows for build host and board host
configuration: screen controllers, renderers, screen state, remote project
location browsing, and remote project file selection.

The component uses `components.host_config.api` for host field policy and build
host draft creation rules. Other components should call the interactive
workflows through `components.host_config_ui.api`.
