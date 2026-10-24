# Configuration Profiles Component

Owns normalization and active-profile synchronization for build hosts, board
access hosts, physical boards, and project profiles.

`board_hosts` contains access hosts. SSH, workspace, TFTP, NFS, deploy-path,
and `server_ip` settings belong to the host. Each host has a `boards` list whose
entries own the physical board identity, board type, serial console, UFS
settings, board IP/MAC, and command overrides. `active_board_host` selects the
access host and `active_board` selects one of its physical boards.

Normalization migrates the former flat board-host records by grouping records
with the same access settings and retaining each old profile name as the
physical board ID. The legacy `board_host` view remains a resolved snapshot of
the active host and board for older runtime consumers.

The component operates on configuration dictionaries. File IO, environment
overrides, and application defaults are passed in from the application layer so
profile normalization remains deterministic and easy to test.
