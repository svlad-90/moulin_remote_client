# Project Mappings

Project mappings describe the remote product paths that are synchronized into
the local overlay. They are stored on the active project profile so each
project configuration can keep its own mapping list and active subset.

`ProjectMappingCoreService` lives in `src/core.py` and owns core mapping CRUD
use cases: listing mappings from active project configuration, adding mappings,
persisting a new mapping, adding from a tree entry, and removing mappings by
name or remote path while keeping active selections in sync.

`ProjectMappingModelService` lives in `src/model.py` and owns mapping path
normalization plus conversion from raw project configuration into normalized
mapping dictionaries.

`ProjectMappingPresentationService` lives in `src/presentation.py` and owns
browser and selection display policy: path marks, mapping drafts, browser row
labels, selection row labels, detail panels, and mapped/selected state labels.

`ProjectOverlayValidationService` lives in `src/overlay.py` and owns validation
of local overlay paths for active mappings. Sync planning and UI status use it
through the narrow project APIs instead of depending on compatibility helpers.

`ProjectMappingSelectionService` lives in `src/selection.py` and owns active
mapping selection use cases: reading and persisting the active mapping subset,
reporting active mapping state, and the selection-screen operations that
toggle, select all, clear, delete, or interpret selection keys.

`ProjectCliWorkflowService` lives in `src/cli_workflow.py` and owns
command-line project workflows: project status, mapping listing, active mapping
selection, selection input parsing, inventory fetch, inventory choose, and
command routing for `status`, `mappings`, `select-mappings`, `inventory`, and
`choose`.

`ProjectInventoryService` lives in `src/inventory.py` and owns inventory fetch
and choose workflows: range parsing, inventory text parsing, choice formatting,
selection file writes, and CLI status output for inventory commands.

`ProjectBrowserWorkflowService` lives in `src/browser_workflow.py` and owns
project-tree browser use cases: path state for mapped and selected entries,
current-entry clamping, add/remove toggle actions from tree entries, and browser
key interpretation. It delegates display decisions to
`ProjectMappingPresentationService`.

Interactive curses mapping screens moved to the `project_mapping_ui` component.
`project` keeps the mapping domain services and exposes them through
`components.project.api` for UI and sync workflow callers.

The old broad `mappings` compatibility modules were removed after runtime
callers moved to the focused services above. Tests that still assert legacy
helper behavior use a test-local adapter.
