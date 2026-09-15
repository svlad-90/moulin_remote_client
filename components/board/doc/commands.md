# Board Command Services

Board-host command construction is split by use case and exposed through narrow
service APIs.

`BoardCommandBuilder` owns shared board command construction: board SSH argv
construction, helper deployment, work directory preparation, and remote shell
path quoting. It is intentionally lower-level than the component services.

`BoardSessionCommandService` lives in `src/session.py` and owns board-host SSH
session use cases: checking board SSH access and opening an interactive board
host shell.

`BoardArtifactTransferService` lives in `src/transfer.py` and owns the
copy-build-artifacts use case: parsing requested artifact targets, resolving
manifest-backed artifact paths, building transfer scripts, and choosing direct
build-host to board-host copy versus client-mediated copy.

`BoardFlashCommandService` lives in `src/flash.py` and owns board flashing use
cases: flashing bootloaders from copied boot artifacts and flashing the UFS
image through the vendored imager helper.

Other components should prefer `BoardCommandWorkflowService` for complete
board-host scenarios. Tests and closely related board code may use the
lower-level services directly when they need to verify command construction.

The old `commands` and `planner` compatibility facades were removed after all
runtime callers moved to service APIs.
