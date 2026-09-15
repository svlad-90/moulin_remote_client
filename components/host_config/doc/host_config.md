# Host Configuration

The host configuration component owns build host and board host field policies,
host field services, and build host draft creation rules.

Interactive TUI workflows moved to the `host_config_ui` component. Runtime code
should use `components.host_config.api` for host policy/domain services and
`components.host_config_ui.api` for screens, renderers, screen state, and remote
browser workflows.
