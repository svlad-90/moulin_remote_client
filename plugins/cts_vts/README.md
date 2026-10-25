# CTS & VTS plugin

The plugin prepares and supervises Android CTS and VTS runs from a dedicated
test-runner host. Enable it in the Moulin Remote Client settings to add the
`CTS&VTS` tab.

Configuration is split into reusable named records:

- a runner profile defines one test-runner SSH endpoint and its remote
  workspace; one profile is marked active for interactive configuration;
- a board profile selects configured board hosts and may assign a static ADB
  serial override;
- a test profile selects CTS, VTS, or both, suite arguments, initial module
  exclusions, and recovery limits;
- a product profile selects a configured build host and project; build targets
  and the Android build context come from that project's effective Moulin
  configuration;
- a test run binds runner, board, test, and product profiles and owns an
  isolated directory on the selected test runner.

`Prepare test run` can build the selected product, flash its boards, and deploy
test artifacts independently. CTS revisions are read from the official Android
CTS downloads page. For VTS, the Moulin layer resolves the Android component,
lunch target, and prebuilt kernel environment. The plugin adds the
`make vts -j` goal and transfers the resulting test package.

The deployed `runner_agent.py` starts under `tmux`, so loss of the Moulin
Remote Client SSH connection does not stop Tradefed. It records state in
`state.json`, logs every attempt, retries `NOT_EXECUTED` tests by session ID,
monitors ADB, and applies the configured reboot, board-type reflash, and
module-exclusion limits when module completion stops advancing.

Runner prerequisites are `python3`, `tmux`, `adb`, `curl`, and `unzip`. Reboot
and reflash are board capabilities selected together with the product; their
commands are not stored in a board profile. Preparing a run copies required
artifacts and helpers to the board host, then stores repeatable operation argv
in the detached run plan. The test runner executes that argv directly without
a shell, so it also needs SSH access to every selected board host.
Build-host to runner VTS transfer currently uses SSH from the workstation, so
both hosts must be reachable from the machine running Moulin Remote Client.

An ADB serial override takes precedence when configured. Otherwise the selected
product type supplies a resolver command that runs on the board access host
immediately before status, prepare, and start operations. The
`gen5_xen_android` resolver maps the configured board MAC through the board
host neighbor table and uses the resulting DomD endpoint on port 5555. When no
MAC is configured, it falls back to the board IP. This keeps DHCP-derived DomD
addresses out of the CTS/VTS board profile.

`Available boards` resolves every device from the configured board profiles
and probes it from the active test runner. The screen reports board power,
serial-console, Dom0, DomD, and ADB stages separately. `Enter` checks one
board, `s` checks the selected board-profile subset, and `a` or `r` checks all
boards. For reachable devices it also shows the resolved ADB serial, Android
serial, build ID, incremental build number, and build fingerprint. Resolver
failures remain attached to their individual boards so one unavailable board
does not hide the others.

Tradefed references:

- https://source.android.com/docs/compatibility/cts/downloads
- https://source.android.com/docs/core/tests/vts/systems
- https://source.android.com/docs/core/tests/vts/setup11
- https://source.android.com/docs/core/tests/tradefed/testing/through-suite/suite-retry
