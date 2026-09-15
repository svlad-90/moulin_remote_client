"""Project git-ref selection service API."""

from __future__ import annotations

from components.project_config_ui.src.project_git_ref import (
    ProjectGitRefSelector,
    project_git_ref_selector_for_config,
)

__all__ = [
    "ProjectGitRefSelector",
    "project_git_ref_selector_for_config",
]
