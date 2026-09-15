"""Public API for sync command display formatting."""

from __future__ import annotations

from components.sync.src.display import SyncCommandDisplayService, sync_command_display_service

sanitize_log_line = sync_command_display_service().sanitize_log_line

__all__ = [
    "SyncCommandDisplayService",
    "sanitize_log_line",
    "sync_command_display_service",
]
