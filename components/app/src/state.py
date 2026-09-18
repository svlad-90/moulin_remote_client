"""Application state workflow controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from components.config.api import accessors as config_accessors
from components.build_runtime.api import env as config_env
from components.build_runtime.api import runtime as config_runtime
from components.moulin.api import manifest as moulin_manifest
from components.project.api import selection as project_selection_api


class AppStateController:
    """Coordinate runtime state, mapping cache, and profile lifecycle."""

    def __init__(
        self,
        *,
        app_dir: Path,
        env: Mapping[str, str],
        default_docker_image: str,
        default_build_targets: str,
        default_moulin_manifest: str,
        remote_read_project_file: Callable[..., Any],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
        profile_slow_ms: float,
        monotonic: Callable[[], float],
    ) -> None:
        self.app_dir = app_dir
        self.env = env
        self.default_docker_image = default_docker_image
        self.default_build_targets = default_build_targets
        self.default_moulin_manifest = default_moulin_manifest
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.profile_slow_ms = profile_slow_ms
        self.monotonic = monotonic
        self.mapping_selection_service = project_selection_api.project_mapping_selection_service()

    def initialize(self, port: Any) -> None:
        self.load_active_project_runtime(port)
        port.mapping_selection_cache = []
        self.refresh_mapping_selection_cache(port)
        self.initialize_ui_profile(port)

    def initialize_session(
        self,
        port: Any,
        *,
        build_items: Callable[[Any], list[Any]],
        reset_preflight: Callable[[Any], Any],
    ) -> None:
        self.load_initial_project_runtime(port)
        port.connection_state = "disconnected"
        port.board_connection_state = "disconnected"
        port.auto_connect_done = False
        port.pending_auto_board_connect = False
        port.action_running = False
        port.active_job = None
        port.last_job = None
        port.last_jobs_by_label = {}
        port.board_job = None
        port.last_board_job = None
        port.last_board_jobs_by_label = {}
        port.preflight_values = {}
        port.status = "Disconnected"
        reset_preflight(port)
        port.selected = 0
        port.menu_scroll = 0
        port.menu_focus = "items"
        port.active_menu_tab = ""
        port.focus_panel = "actions"
        port.log_scroll = 0
        port.log_follow = True
        port.logs_expanded = False
        port.focus_before_logs_expanded = "actions"
        port.last_exit = None
        port.done = False
        port.items = build_items(port)
        port.menu_dirty = True
        port.main_full_redraw = True
        port.render_cache = {}
        port.logs_dirty = True
        port.last_log_render_at = 0.0
        port.mapping_selection_cache = []
        self.refresh_mapping_selection_cache(port)
        port.ui_profile_enabled = False
        port.ui_profile_path = self.app_dir / "workspace" / "ui-profile.log"
        port.ui_profile_buffer = []
        port.ui_profile_last_flush = self.monotonic()
        self.initialize_ui_profile(port)

    def load_initial_project_runtime(self, port: Any) -> None:
        context = config_runtime.build_runtime_context_for_config(
            port.config,
            app_dir=self.app_dir,
            env=self.env,
            default_docker_image=self.default_docker_image,
            default_build_targets=self.default_build_targets,
            default_parameters=lambda: {},
        )
        port.docker_image = str(context["docker_image"])
        port.build_params = dict(context["build_params"])
        port.build_targets = str(context["build_targets"]) or config_env.build_targets_from_env(self.env, self.default_build_targets)
        port.board_artifacts = str(context["board_artifacts"]) or port.build_targets

    def load_active_project_runtime(self, port: Any) -> None:
        context = moulin_manifest.build_runtime_context_for_config(
            port.config,
            app_dir=self.app_dir,
            env=self.env,
            default_docker_image=self.default_docker_image,
            default_build_targets=self.default_build_targets,
            default_moulin_manifest=self.default_moulin_manifest,
            remote_read_project_file=self.remote_read_project_file,
            cache=self.manifest_cache,
        )
        port.docker_image = str(context["docker_image"])
        port.build_params = dict(context["build_params"])
        port.build_targets = str(context["build_targets"])
        port.board_artifacts = str(context["board_artifacts"])

    def refresh_mapping_selection_cache(self, port: Any) -> None:
        port.mapping_selection_cache = self.mapping_selection_service.read_mapping_selection_for_config(
            port.config,
            config_accessors.mapping_selection_path_for_config(port.config, self.app_dir),
            required=False,
        )
        if hasattr(port, "render_cache"):
            port.render_cache.pop("details", None)

    def initialize_ui_profile(self, port: Any) -> None:
        port.ui_profile_enabled = self.env.get("MOULIN_REMOTE_UI_PROFILE", "").strip().lower() in {"1", "yes", "true", "on"}
        port.ui_profile_path = Path(
            self.env.get(
                "MOULIN_REMOTE_UI_PROFILE_PATH",
                str(self.app_dir / "workspace" / "ui-profile.log"),
            )
        )
        port.ui_profile_buffer = []
        port.ui_profile_last_flush = self.monotonic()
        if port.ui_profile_enabled:
            self.profile(port, "profile-start", path=str(port.ui_profile_path))

    def profile(self, port: Any, event: str, **fields: Any) -> None:
        if not getattr(port, "ui_profile_enabled", False):
            return
        now = self.monotonic()
        parts = [f"{now:.6f}", event]
        for key, value in fields.items():
            value_text = str(value)
            if any(char.isspace() for char in value_text):
                value_text = repr(value_text)
            parts.append(f"{key}={value_text}")
        port.ui_profile_buffer.append(" ".join(parts))
        if len(port.ui_profile_buffer) >= 50 or now - port.ui_profile_last_flush > 1.0:
            self.flush_profile(port)

    def profile_slow(self, port: Any, event: str, started: float, threshold_ms: float | None = None, **fields: Any) -> float:
        elapsed_ms = (self.monotonic() - started) * 1000.0
        effective_threshold_ms = self.profile_slow_ms if threshold_ms is None else threshold_ms
        if elapsed_ms >= effective_threshold_ms:
            self.profile(port, event, ms=f"{elapsed_ms:.1f}", **fields)
        return elapsed_ms

    def flush_profile(self, port: Any) -> None:
        if not getattr(port, "ui_profile_enabled", False) or not port.ui_profile_buffer:
            return
        try:
            port.ui_profile_path.parent.mkdir(parents=True, exist_ok=True)
            with port.ui_profile_path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(port.ui_profile_buffer) + "\n")
            port.ui_profile_buffer.clear()
            port.ui_profile_last_flush = self.monotonic()
        except Exception:
            port.ui_profile_enabled = False

    def quit(self, port: Any) -> None:
        self.flush_profile(port)
        port.done = True


def app_state_controller(
    *,
    app_dir: Path,
    env: Mapping[str, str],
    default_docker_image: str,
    default_build_targets: str,
    default_moulin_manifest: str,
    remote_read_project_file: Callable[..., Any],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    profile_slow_ms: float,
    monotonic: Callable[[], float],
) -> AppStateController:
    return AppStateController(
        app_dir=app_dir,
        env=env,
        default_docker_image=default_docker_image,
        default_build_targets=default_build_targets,
        default_moulin_manifest=default_moulin_manifest,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
        profile_slow_ms=profile_slow_ms,
        monotonic=monotonic,
    )
