# Host Configuration

The host configuration component owns build host, board access host, and
physical board field policies, host field services, and build host draft
creation rules. A board access host contains shared SSH/TFTP/NFS settings and
one or more physical boards. `server_ip` is shared because it identifies that
host as seen by U-Boot; console devices, board IP/MAC, UFS settings, board type,
and command overrides belong to each physical board.

Interactive TUI workflows moved to the `host_config_ui` component. Runtime code
should use `components.host_config.api` for host policy/domain services and
`components.host_config_ui.api` for screens, renderers, screen state, and remote
browser workflows.
