#!/usr/bin/env python3
"""Local TUI client for remote Moulin product development."""

from __future__ import annotations

import curses
import os
import sys
import time
from pathlib import Path
from typing import Any

from components.app.api import bootstrap as app_bootstrap_api
from components.moulin.api import manifest as moulin_manifest_api
from components.ui.api.menu import MenuItem


os.environ.setdefault("ESCDELAY", "100")

APP_DIR = Path(__file__).resolve().parent
BOARD_TOOLS_DIR = APP_DIR / "board_tools"
FLASH_BOOTLOADERS_TOOL = BOARD_TOOLS_DIR / "flash_bootloaders.py"
XT_IMAGER_TOOL = BOARD_TOOLS_DIR / "xt-imager.py"
DEFAULT_CONFIG = APP_DIR / "moulin_remote_client.config.json"
DEFAULT_CONFIG_EXAMPLE = APP_DIR / "moulin_remote_client.config.example.json"
DEFAULT_DOCKER_IMAGE = ""
DEFAULT_DOCKERFILE = "doc/Dockerfile"
DEFAULT_BUILD_TARGETS = ""
DEFAULT_MOULIN_MANIFEST = "product.yaml"
UI_PROFILE_SLOW_MS = 20.0
MANIFEST_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}
MoulinYamlLoader = moulin_manifest_api.MoulinYamlLoader


BOOTSTRAP = app_bootstrap_api.app_bootstrap_controller(
    app_bootstrap_api.AppBootstrapSettings(
        app_dir=APP_DIR,
        default_config=DEFAULT_CONFIG,
        default_config_example=DEFAULT_CONFIG_EXAMPLE,
        default_docker_image=DEFAULT_DOCKER_IMAGE,
        default_dockerfile=DEFAULT_DOCKERFILE,
        default_build_targets=DEFAULT_BUILD_TARGETS,
        default_moulin_manifest=DEFAULT_MOULIN_MANIFEST,
        flash_bootloaders_tool=FLASH_BOOTLOADERS_TOOL,
        xt_imager_tool=XT_IMAGER_TOOL,
        profile_slow_ms=UI_PROFILE_SLOW_MS,
    ),
    env=os.environ,
    manifest_cache=MANIFEST_CACHE,
    curses_wrapper=curses.wrapper,
    read_input=input,
    write_line=print,
    monotonic=time.monotonic,
)

REMOTE_PROJECT_FILE_READER = BOOTSTRAP.remote_project_file_reader
LOAD_CONFIG = BOOTSTRAP.load_config
SAVE_CONFIG = BOOTSTRAP.save_config
CLI_RUNTIME_CONTEXT = BOOTSTRAP.cli_runtime_context
ClientApp = BOOTSTRAP.client_app_class()


def main(argv: list[str]) -> int:
    return BOOTSTRAP.run(argv, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
