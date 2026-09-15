# Sync Commands

The sync component builds file synchronization commands from project mappings.
It does not execute commands and does not know about curses UI state.

`SyncMappingCommandService` owns mapped-file sync command plans. Use it when the
caller already knows it is working with project mappings rather than generic
selected paths or build sequencing.

`SyncSelectedPathService` owns selected project-tree path sync command plans.
Use it for inventory-based pull/push commands where paths are copied with
rsync `--relative`.

`SyncPreBuildService` owns the command sequence used before product builds:
save current build settings, push active mappings, and append the build command.

`SyncCliService` owns CLI dispatch for sync verbs. It chooses selected-path,
mapping, or selected-mapping sync and runs the resulting command plans.

Inputs from other domains should be passed explicitly:

- normalized mapping dictionaries from the project component;
- local overlay base path;
- remote project base path;
- already-expanded exclude flags.
