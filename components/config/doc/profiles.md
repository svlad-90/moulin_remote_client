# Configuration Profiles Component

Owns normalization and active-profile synchronization for build hosts, board
hosts, and project profiles.

The component operates on configuration dictionaries. File IO, environment
overrides, and application defaults are passed in from the application layer so
profile normalization remains deterministic and easy to test.
