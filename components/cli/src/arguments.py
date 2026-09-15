"""Command-line argument parsing."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser(description: str | None, default_config: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, default=default_config)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connect")
    sub.add_parser("server-tui")
    sub.add_parser("sync-menu")
    sub.add_parser("menu")
    sub.add_parser("remote-status")
    sub.add_parser("build-docker")
    sub.add_parser("regen-moulin")
    sub.add_parser("build")
    sub.add_parser("status")
    sub.add_parser("mappings")
    sub.add_parser("select-mappings")
    sub.add_parser("inventory")
    sub.add_parser("choose")
    sub.add_parser("pull")
    sub.add_parser("pull-dry-run")
    sub.add_parser("push")
    sub.add_parser("push-dry-run")
    pull_map = sub.add_parser("pull-map")
    pull_map.add_argument("names", nargs="+", help="mapping names, or 'all'")
    pull_map_dry = sub.add_parser("pull-map-dry-run")
    pull_map_dry.add_argument("names", nargs="+", help="mapping names, or 'all'")
    push_map = sub.add_parser("push-map")
    push_map.add_argument("names", nargs="+", help="mapping names, or 'all'")
    push_map_dry = sub.add_parser("push-map-dry-run")
    push_map_dry.add_argument("names", nargs="+", help="mapping names, or 'all'")
    sub.add_parser("pull-selected-map")
    sub.add_parser("pull-selected-map-dry-run")
    sub.add_parser("push-selected-map")
    sub.add_parser("push-selected-map-dry-run")
    sub.add_parser("tui")
    return parser


def parse_args(argv: list[str], *, description: str | None, default_config: Path) -> argparse.Namespace:
    return build_parser(description, default_config).parse_args(argv)
