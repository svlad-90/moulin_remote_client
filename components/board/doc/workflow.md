# Board Command Workflow

`BoardCommandWorkflowService` is the service boundary for board-host use cases.
Other components should ask it for complete command plans instead of composing
board helper functions directly. It coordinates smaller board services and
shares only the low-level `BoardCommandBuilder` command construction primitive
with them.

Current use cases:

- check or open a board-host SSH session;
- open an interactive board-host shell;
- copy configured build artifacts to the board host;
- flash bootloaders from copied boot artifacts;
- flash the UFS image from copied artifacts.

`BoardSessionCommandService` owns board-host connection and shell command use
cases.

`BoardArtifactTransferService` owns the copy-build-artifacts use case, including
target parsing, manifest-backed artifact resolution, and transfer route
selection.

`BoardFlashCommandService` owns bootloader and UFS flashing command plans.

`BoardCommandBuilder` owns shared SSH/path/tool deployment primitives. It is an
internal building block for services, not the public board-component boundary.

The old `BoardCommandPlanner` and lower-level `commands` compatibility facades
were removed. New component code should use the workflow service or one of the
use-case services directly.
