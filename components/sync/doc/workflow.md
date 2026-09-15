# Sync Workflow

`SyncWorkflowController` owns the interactive mapped-file sync screen.

`SyncCommandWorkflowService` owns sync-aware command sequencing for build
commands. It saves the current build settings, resolves the active mapping
selection path, prepends pre-build push commands when mappings are active, and
then appends the requested build command.

Other components should call this service instead of passing sync command
builder details through menu or job layers.

`SyncMappingCommandService` owns mapped-file rsync use cases: one mapping,
mapping plans with log headers, selected mappings, and all mappings.

`SyncSelectedPathService` owns explicitly selected project-tree path sync use
cases from the inventory selection file: selected-path pull, selected-path
push, missing local path checks, and runner dispatch.

`SyncPreBuildService` owns automatic pre-build mapping push and build command
sequencing. It validates the local overlay, converts mapping push failures into
log commands, saves current build settings, and appends the requested build
command.

`SyncCliService` owns sync CLI dispatch. It routes selected-path and mapped-file
sync verbs to the services above and executes mapping command plans through the
provided runner/write-line callbacks.

`SyncCommandPlanner` coordinates these services for higher-level callers that
need selected paths, mapped-file sync, pre-build sequencing, and CLI dispatch
behind one service boundary.

The old `commands` compatibility facade was removed after runtime callers and
tests moved to the service APIs.
