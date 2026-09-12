# Moulin Remote Client

Local terminal UI for remote Moulin product development.

The client is project-agnostic. Configure a remote machine, target checkout
directory, project Git URL, optional Docker image name, Moulin manifest, build
targets, and source mappings. Then use the TUI to prepare the remote checkout,
run Moulin, run Ninja targets, open a remote shell, and sync selected files
between the local overlay and the remote checkout.

## Run

```sh
./moulin_remote_client.py menu
```

Start with `Remote configurations` in the TUI. The screen is centered on the
remote profile list: select a profile and press `Enter` to edit its fields.
Use `a` to add a blank profile, `d` to delete the selected profile, and `s` to
make the selected profile active.

- SSH user and host
- remote project directory
- project Git URL
- multiple named remote profiles

The setup flow is progressive. Until an SSH user is set, host-dependent actions
stay disabled. Until an SSH host is set, connect-dependent actions stay
disabled. After SSH connection succeeds, the remote directory browser can be
used to select the target checkout directory.

Use `s` in the TUI to edit build settings:

- local overlay directory
- Moulin manifest path
- Docker image name
- build targets and Moulin parameters discovered from the manifest

The `Prepare remote project` action clones the active remote profile Git URL
into the active remote profile project directory when the target directory is
missing.

## Config

Default local config path:

```text
moulin_remote_client.config.json
```

This file is local state and is ignored by Git. If it does not exist, the
client starts from `moulin_remote_client.config.example.json` and writes local
changes to `moulin_remote_client.config.json`.

Useful environment overrides:

```sh
MOULIN_REMOTE_SSH_USER=builder
MOULIN_REMOTE_SSH_HOST=build-host
MOULIN_REMOTE_PROJECT_DIR=/mnt/storage/user/projects/product
MOULIN_REMOTE_PROJECT_GIT_URL=git@example.com:org/product.git
MOULIN_REMOTE_DOCKER_IMAGE=product-build
MOULIN_REMOTE_BUILD_TARGETS="full.img.gz boot_artifacts"
MOULIN_REMOTE_AUTO_CONNECT=no
```

## Source Mappings

`Sync mapped files` manages named mappings between the remote checkout and the
local overlay. `Add mapping` opens a remote project tree picker, lists files and
directories, and can save selected paths as mappings. `Pull selected` copies
from remote to local; `Push selected` copies local edits back to remote.

The config is intentionally generic. Do not commit product-specific paths,
hosts, image names, or credentials unless they are sample placeholders.
