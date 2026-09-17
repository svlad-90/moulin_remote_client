# Sync Workflow

`SyncWorkflowController` owns the interactive mapped-file sync screen.

`SyncCommandWorkflowService` owns sync-aware command sequencing for build
commands. It saves the current build settings for build commands, and exposes
an explicit mapped-file push sequence for the main menu copy action.

Other components should call this service instead of passing sync command
builder details through menu or job layers.

`SyncMappingCommandService` owns mapped-file rsync use cases: one mapping,
mapping plans with log headers, selected mappings, and all mappings.

`SyncSelectedPathService` owns explicitly selected project-tree path sync use
cases from the inventory selection file: selected-path pull, selected-path
push, missing local path checks, and runner dispatch.

`SyncPreBuildService` owns explicit mapped-file push and build setting
persistence. It validates the local overlay, converts mapping push failures
into log commands, saves current build settings, and returns the requested
build command without adding an implicit copy step.

`SyncCliService` owns sync CLI dispatch. It routes selected-path and mapped-file
sync verbs to the services above and executes mapping command plans through the
provided runner/write-line callbacks.

`SyncCommandPlanner` coordinates these services for higher-level callers that
need selected paths, mapped-file sync, build setting persistence, and CLI dispatch
behind one service boundary.

The old `commands` compatibility facade was removed after runtime callers and
tests moved to the service APIs.
