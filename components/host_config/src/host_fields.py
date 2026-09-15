"""Build and board host field services."""

from __future__ import annotations

from typing import Any

from components.board_types.api import registry as board_type_registry_api
from components.config.api import accessors
from components.config.api import profiles as config_profiles


class BoardHostFieldService:
    """Own board host field update and availability use cases."""

    def normalize_value(self, key: str, value: str) -> str:
        value = value.strip()
        if key == "direct_copy":
            return "yes" if value.lower() in {"1", "true", "yes", "on"} else "no"
        return value

    def next_direct_copy_value(self, current: str) -> str:
        return "no" if current.strip().lower() in {"1", "true", "yes", "on"} else "yes"

    def available_board_type_options(self) -> list[dict[str, str]]:
        return [
            {
                "type": adapter.type_id,
                "label": adapter.label or adapter.type_id,
                "description": adapter.description,
            }
            for adapter in board_type_registry_api.board_type_registry().adapters()
        ]

    def available_board_types(self) -> list[str]:
        return [option["type"] for option in self.available_board_type_options()]

    def next_board_type_value(self, current: str) -> str:
        board_types = self.available_board_types()
        if not board_types:
            return "gen5_x5h"
        clean_current = current.strip()
        if clean_current not in board_types:
            return board_types[0]
        return board_types[(board_types.index(clean_current) + 1) % len(board_types)]

    def connection_reset_needed(self, key: str, host_name: str, active_board_host: str) -> bool:
        return key in ("type", "user", "host", "work_dir") and str(host_name) == str(active_board_host)

    def apply_inline_field_update_for_config(
        self,
        config: dict[str, Any],
        host: dict[str, Any],
        key: str,
        raw_value: str,
    ) -> dict[str, Any]:
        value = self.normalize_value(key, raw_value)
        config_profiles.update_board_host_profile_field(config, host, key, value)
        return {
            "value": value,
            "status": f"{key} updated",
            "connection_reset": self.connection_reset_needed(
                key,
                str(host.get("name", "")),
                str(config.get("active_board_host", "")),
            ),
        }

    def apply_direct_copy_toggle_for_config(self, config: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
        value = self.next_direct_copy_value(str(host.get("direct_copy", "no")))
        config_profiles.update_board_host_profile_field(config, host, "direct_copy", value)
        return {
            "value": value,
            "status": f"Direct copy: {value}",
        }

    def field_enabled(self, key: str, host: dict[str, Any]) -> bool:
        if key in (
            "name",
            "label",
            "type",
            "user",
            "work_dir",
            "console_device",
            "ufs_loadaddr",
            "ufs_buffersize",
            "direct_copy",
        ):
            return True
        if key == "host":
            return bool(str(host.get("user", "")).strip())
        return True

    def field_disabled_reason(self, key: str, host: dict[str, Any]) -> str:
        if key == "host":
            return "set SSH user first"
        return ""

    def field_hint(self, key: str) -> str:
        hints = {
            "name": "Unique local board host profile id. Renaming an active profile preserves active selection.",
            "label": "Display label shown in the main client header.",
            "type": "Enter/Space selects board type. Available: " + ", ".join(self.available_board_types()),
            "user": "SSH user for the board access host.",
            "host": "SSH host name or IP address for board access.",
            "work_dir": "Working directory on the board host for copied artifacts and deployed helper scripts.",
            "console_device": "Serial console device. Leave empty to auto-detect the first /dev/GEN5_CONSOLE* on the board host.",
            "ufs_loadaddr": "Optional xt-imager --loadaddr override. Leave empty to use xt-imager default.",
            "ufs_buffersize": "Optional xt-imager --buffersize override. Leave empty to use xt-imager default.",
            "direct_copy": "Enter/Space toggles yes when the build host can SSH to this board host directly.",
        }
        return hints.get(key, "")


class BuildHostFieldService:
    """Own build host field update and availability use cases."""

    def normalize_value(self, key: str, value: str) -> str:
        return value.strip()

    def connection_reset_needed(self, key: str, remote_name: str, active_remote: str) -> bool:
        return key in ("user", "host", "projects_dir") and str(remote_name) == str(active_remote)

    def apply_inline_field_update_for_config(
        self,
        config: dict[str, Any],
        remote: dict[str, Any],
        key: str,
        raw_value: str,
    ) -> dict[str, Any]:
        value = self.normalize_value(key, raw_value)
        config_profiles.update_remote_profile_field(config, remote, key, value)
        return {
            "value": value,
            "status": f"{key} updated",
            "connection_reset": self.connection_reset_needed(
                key,
                str(remote.get("name", "")),
                str(config.get("active_remote", "")),
            ),
        }

    def apply_labeled_field_update_for_config(
        self,
        config: dict[str, Any],
        remote: dict[str, Any],
        key: str,
        raw_value: str,
        label: str,
    ) -> dict[str, Any]:
        plan = self.apply_inline_field_update_for_config(config, remote, key, raw_value)
        return {
            **plan,
            "status": f"{label} updated",
        }

    def apply_projects_dir_selection_for_config(
        self,
        config: dict[str, Any],
        remote: dict[str, Any],
        selected: str,
    ) -> dict[str, Any]:
        remote["projects_dir"] = selected
        config_profiles.sync_active_remote(config)
        return {
            "status": f"Projects dir: {selected}",
        }

    def field_enabled(self, key: str, remote: dict[str, Any], *, active_remote: str, connected: bool) -> bool:
        if key in ("back", "name", "label", "user", "projects_dir"):
            return True
        if key == "host":
            return bool(str(remote.get("user", "")).strip())
        if key in ("moulin_manifest", "dockerfile"):
            return str(remote.get("name", "")) == str(active_remote) and connected
        return True

    def field_disabled_reason(
        self,
        key: str,
        remote: dict[str, Any],
        *,
        active_remote: str,
        remote_has_project_dir: bool,
    ) -> str:
        if key == "host":
            return "set SSH user first"
        if key in ("moulin_manifest", "dockerfile"):
            if str(remote.get("name", "")) != str(active_remote):
                return "set this remote active first"
            if not str(remote.get("user", "")).strip():
                return "set SSH user first"
            if not str(remote.get("host", "")).strip():
                return "set SSH host first"
            if not remote_has_project_dir:
                return "set projects dir and project dir first"
            return "connect to the build host first"
        return ""

    def field_hint(self, key: str) -> str:
        hints = {
            "name": "Unique local profile id. Renaming an active profile preserves active selection.",
            "label": "Display label shown in the main client header.",
            "user": "SSH user for the remote build machine.",
            "host": "SSH host name or IP address.",
            "projects_dir": "Base directory on the build host that contains project checkouts. Use Enter or b to browse after connect.",
            "back": "Return to the remote list.",
        }
        return hints.get(key, "")

    def field_enabled_for_config(
        self,
        key: str,
        remote: dict[str, Any],
        config: dict[str, Any],
        *,
        connected: bool,
    ) -> bool:
        return self.field_enabled(
            key,
            remote,
            active_remote=str(config.get("active_remote", "")),
            connected=connected,
        )

    def field_disabled_reason_for_config(
        self,
        key: str,
        remote: dict[str, Any],
        config: dict[str, Any],
    ) -> str:
        return self.field_disabled_reason(
            key,
            remote,
            active_remote=str(config.get("active_remote", "")),
            remote_has_project_dir=accessors.remote_has_project_dir_for_config(config),
        )


def board_host_field_service() -> BoardHostFieldService:
    return BoardHostFieldService()


def build_host_field_service() -> BuildHostFieldService:
    return BuildHostFieldService()
