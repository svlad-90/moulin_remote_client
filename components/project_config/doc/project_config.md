# Project Configuration

The project configuration component owns project field policies, settings
policy, target policy, and project-related action services.

Interactive TUI workflows moved to the `project_config_ui` component. Runtime
code should use `components.project_config.api` for project policy/domain
services and `components.project_config_ui.api` for screens, renderers, screen
state, target selection, git-ref selection, and project picking workflows.
