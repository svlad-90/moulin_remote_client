# Project Configuration UI

`project_config_ui` owns interactive TUI workflows for project configuration:
the project profile screen, project screen renderer/state, build target and
board artifact selection, project git-ref selection, and project profile picker.

The component uses `components.project_config.api` for project field policy,
settings services, and action services. Other components should call the
interactive workflows through `components.project_config_ui.api`.
