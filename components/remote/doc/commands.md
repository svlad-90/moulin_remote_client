# Remote Commands Component

Owns argv/script construction for build-host SSH operations, product docker
commands, and remote project discovery.

`RemoteSessionCommandService` lives in `src/session.py` and owns build-host SSH
session use cases: checking SSH access, wrapping project-directory remote shell
commands, and opening an interactive build-host shell.

`RemoteProjectMaintenanceService` lives in `src/project.py` and owns remote
project maintenance use cases: preparing or repairing the configured checkout,
checking out the configured Git ref, and project preflight checks.

`RemoteProjectDiscoveryService` lives in `src/discovery.py` and owns remote
project inspection use cases: reading files from the build host, inventory
commands, project tree/listing commands and parsers, remote directory browsing,
remote home discovery, git tracked files, YAML/Dockerfile candidates, Dockerfile
validation, and branch listing.

`RemoteBuildCommandService` lives in `src/build.py` and owns build-host
build use cases: Docker image build, Moulin regeneration, product build, remote
status, and CLI command routing for build-host actions.

The old `commands` and `planner` compatibility facades were removed after
runtime callers and tests moved to service APIs.

The API takes already-resolved scalar values such as host spec, project
directory, docker image, manifest name, build parameters, and targets.

Configuration lookup, UI status parsing, and command execution remain in the
application layer.
