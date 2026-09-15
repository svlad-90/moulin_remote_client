# Build Host Command Workflow

`RemoteCommandWorkflowService` is the service boundary for build-host command
use cases. Menu and application components should request complete command
plans from this service instead of composing remote command builder calls. It
aggregates smaller use-case services rather than owning shell construction
itself.

Current use cases:

- connect and open an interactive build-host shell;
- prepare or repair the remote project checkout;
- checkout the configured Git ref;
- build the Docker image;
- regenerate Moulin/Ninja;
- run the configured product build.

`RemoteSessionCommandService` owns build-host SSH connect, remote shell wrapping,
and interactive shell command plans.

`RemoteProjectMaintenanceService` owns prepare project, checkout Git ref, and
project preflight command plans.

`RemoteBuildCommandService` owns Docker image build, Moulin regeneration, Ninja
build, remote status, and CLI command routing for build-host actions.

The old lower-level `commands` module was removed. New component code should use
the workflow service or one of the use-case services directly.
