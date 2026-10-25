# Board Types

`board_types` owns board-specific behavior adapters. A board host profile
selects a type with its `type` field; when the field is absent the registry
uses `gen5_x5h` so existing configurations keep their behavior.

Adapters expose their available board actions from Python. The main menu builds
`BOARD COMMANDS` from those actions, and `components.board` asks the selected
adapter to produce command plans. UI execution, logging, confirmation, and
job cancellation stay in the common workflow layer.

The utility declares stable `BoardCapability` values. Common capabilities can
be inferred from the adapter contract: a `restart_board` action with non-empty
values for every command listed in its `required_commands` automatically
exposes `board.reboot`. An adapter advertises its remaining capabilities through
`capabilities()` and materializes every operation through
`operation_plan()`. The returned `BoardOperationPlan` explicitly separates
required product build targets, resource provisioning, repeatable operation
commands, an execution timeout, and a board stabilization delay. Consumers
decide how those phases fit their own workflow and must treat every capability
as optional. Board and test profiles must not store replacement shell commands.

Board-specific workflow logic should live in the adapter. Adapters may use
shared helpers from `BoardActionContext`, such as `command_builder` for SSH and
helper deployment argv construction or `transfer_service` for generic artifact
copying, but the action order and board-specific commands belong to the board
type.

Built-in adapters are discovered automatically from Python modules under
`components/board_types/src/builtin/`. To add a board type, add a module there
with a `BoardTypeAdapter` subclass and a non-empty `type_id`; no registry edit
is needed.

The first built-in adapter, `gen5_x5h`, preserves the current GEN5/X5H behavior:
power-cycle the board, copy build artifacts, flash bootloaders, and flash the
UFS image. Its standard `x5h_off` and `x5h_on` commands provide `board.reboot`.
It implements `board.reflash` through the existing UFS flow and
`board.reflash-bootloaders` through the existing bootloader flashing flow.
