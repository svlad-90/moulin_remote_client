# Moulin Manifest Component

Owns pure Moulin manifest behavior: tag detection, manifest shape markers,
parameter defaults, parameter overrides, variable expansion, build target
candidates, and board artifact copy specs.

The public API is intentionally thin and side-effect free. File loading,
configuration lookup, caching, UI, and remote execution stay in the application
entry point until those domains get their own components.
