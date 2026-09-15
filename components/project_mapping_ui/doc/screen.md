# Project Mapping UI

`project_mapping_ui` owns the interactive curses screens for project mappings:
adding mappings from the remote project browser, deleting mappings, and choosing
the active mapping subset.

The component depends on `components.project.api` for mapping domain services.
Other components should call it through `components.project_mapping_ui.api`.
