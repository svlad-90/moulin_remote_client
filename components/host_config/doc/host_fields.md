# Host Field Services

`BuildHostFieldService` owns build-host field use cases: value normalization,
field updates, connection reset decisions, project-directory selection, and
field availability/hint policy.

`BoardHostFieldService` owns board-host field use cases: value normalization,
inline updates, direct-copy toggling, board connection reset decisions, and
field availability/hint policy.

`components.host_config.api.fields` exports both services and factory functions.
Legacy functions in `src/fields.py` remain as compatibility facades for current
tests and existing call sites.
