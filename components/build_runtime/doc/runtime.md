# Build Runtime

The build runtime component owns environment overrides, persisted build
settings, and runtime configuration orchestration used by the app while it
loads or saves the active build context.

Other components import this behavior through `components.build_runtime.api`.
