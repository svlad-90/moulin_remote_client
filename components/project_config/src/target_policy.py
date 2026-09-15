"""Target selection policy service."""

from __future__ import annotations

import shlex
from typing import Any


class TargetSelectionPolicyService:
    """Own build target and board artifact selection rules."""

    def ordered_targets(
        self,
        candidates: list[dict[str, str]],
        selected: set[str],
        current_text: str,
    ) -> list[str]:
        current = [target for target in shlex.split(current_text) if target in selected]
        extra = [
            candidate["target"]
            for candidate in candidates
            if candidate["target"] in selected and candidate["target"] not in current
        ]
        return current + extra

    def ordered_targets_for_text(
        self,
        candidates: list[dict[str, str]],
        selected: set[str],
        *,
        current_text: str | None,
        default_text: str,
    ) -> list[str]:
        return self.ordered_targets(candidates, selected, current_text if current_text is not None else default_text)

    def selected_targets_from_text(self, text: str) -> set[str]:
        return set(shlex.split(text))

    def target_actions(self, candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
        return [{"kind": "target", "candidate": candidate} for candidate in candidates]

    def target_text_for_selection(
        self,
        candidates: list[dict[str, str]],
        selected: set[str],
        *,
        current_text: str | None,
        default_text: str,
    ) -> str:
        return " ".join(
            self.ordered_targets_for_text(
                candidates,
                selected,
                current_text=current_text,
                default_text=default_text,
            )
        )

    def target_display_text(
        self,
        candidates: list[dict[str, str]],
        selected: set[str],
        *,
        current_text: str | None,
        default_text: str,
    ) -> str:
        return self.target_text_for_selection(
            candidates,
            selected,
            current_text=current_text,
            default_text=default_text,
        ) or "none"

    def toggle_target_selection(self, action: dict[str, Any], selected: set[str]) -> tuple[set[str], str]:
        target = action["candidate"]["target"]
        next_selected = set(selected)
        if target in next_selected:
            next_selected.remove(target)
        else:
            next_selected.add(target)
        state = "selected" if target in next_selected else "removed"
        return next_selected, f"{target}: {state}"

    def action_label(self, action: dict[str, Any], selected: set[str]) -> str:
        kind = action["kind"]
        if kind == "target":
            candidate = action["candidate"]
            mark = "x" if candidate["target"] in selected else " "
            source = candidate.get("source", "")
            return f"[{mark}] {candidate['target']} ({source})"
        return str(kind)

    def action_description(self, action: dict[str, Any]) -> str:
        kind = action["kind"]
        if kind == "target":
            candidate = action["candidate"]
            return candidate.get("desc", "") or f"Toggle Ninja target {candidate['target']}."
        return ""


def target_selection_policy_service() -> TargetSelectionPolicyService:
    return TargetSelectionPolicyService()
