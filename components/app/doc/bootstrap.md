# Application Bootstrap

`AppBootstrapController` owns startup wiring for the executable entrypoint:
runtime config loading/saving, remote project file access, CLI runtime context,
the bound `ClientApp` class, and dispatch into the CLI workflow controller.
