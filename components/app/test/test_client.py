from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.app.api import client


class FakeScreen:
    pass


class FakeAppState:
    def __init__(self) -> None:
        self.initialize_calls: list[tuple[Any, Any, Any]] = []
        self.runtime_calls: list[Any] = []
        self.refresh_calls: list[Any] = []
        self.profile_calls: list[tuple[Any, str, dict[str, Any]]] = []
        self.quit_calls: list[Any] = []

    def initialize_session(self, port: Any, *, build_items: Any, reset_preflight: Any) -> None:
        self.initialize_calls.append((port, build_items, reset_preflight))
        port.initialized = True

    def load_active_project_runtime(self, port: Any) -> None:
        self.runtime_calls.append(port)

    def refresh_mapping_selection_cache(self, port: Any) -> None:
        self.refresh_calls.append(port)

    def profile(self, port: Any, event: str, **fields: Any) -> None:
        self.profile_calls.append((port, event, fields))

    def profile_slow(self, _port: Any, _event: str, _started: float, _threshold_ms: float | None = None, **_fields: Any) -> float:
        return 12.5

    def flush_profile(self, port: Any) -> None:
        port.flushed = True

    def quit(self, port: Any) -> None:
        self.quit_calls.append(port)


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def build_items(self, port: Any) -> list[str]:
        self.calls.append(("build", port, None))
        return ["item"]

    def run(self, port: Any) -> None:
        self.calls.append(("run", port, None))

    def handle_main_key(self, port: Any, ch: int) -> None:
        self.calls.append(("key", port, ch))

    def draw(self, port: Any) -> None:
        self.calls.append(("draw", port, None))

    def stop_running_preview(self, _port: Any, slot: str | None = None) -> str:
        return f"preview:{slot}"


class FakeTerminalPort:
    pass


class FakeTerminalAdapter:
    def selected_attr(self) -> int:
        return 7

    def read_key(self, _port: Any) -> int:
        return 113

    def add(self, port: Any, y: int, x: int, text: str, attr: int = 0) -> None:
        port.added = (y, x, text, attr)


class ClientAppFactoryTests(unittest.TestCase):
    def make_dependencies(self, app_dir: Path) -> client.ClientAppDependencies:
        return client.ClientAppDependencies(
            app_dir=app_dir,
            default_config_path=app_dir / "config.json",
            default_docker_image="image",
            default_dockerfile="doc/Dockerfile",
            default_build_targets="target",
            default_moulin_manifest="product.yaml",
            flash_bootloaders_tool=app_dir / "flash.py",
            xt_imager_tool=app_dir / "imager.py",
            remote_read_project_file=Mock(),
            manifest_cache={},
            load_config=Mock(return_value={"reloaded": True}),
            save_config=Mock(),
            env={},
            read_input=Mock(return_value=""),
            write_line=Mock(),
            monotonic=Mock(return_value=1.0),
            profile_slow_ms=20.0,
        )

    def test_bound_client_initializes_session_through_app_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state = FakeAppState()
            fake_services = FakeServices()
            fake_terminal = FakeTerminalPort()
            fake_terminal_adapter = FakeTerminalAdapter()
            ClientApp = client.client_app_class(self.make_dependencies(Path(tmpdir)))

            with (
                patch.object(ClientApp, "app_state_controller", return_value=fake_state),
                patch.object(ClientApp, "app_services_controller", return_value=fake_services),
                patch.object(ClientApp, "terminal_port_controller", return_value=fake_terminal),
                patch.object(ClientApp, "terminal_port_adapter", return_value=fake_terminal_adapter),
            ):
                app = ClientApp(FakeScreen(), {"config": True})

            self.assertTrue(app.initialized)
            self.assertEqual(fake_state.initialize_calls[0][0], app)
            self.assertIs(fake_state.initialize_calls[0][1].__self__, fake_services)
            self.assertEqual(fake_state.initialize_calls[0][1].__name__, "build_items")

    def test_facade_methods_delegate_to_owned_controllers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state = FakeAppState()
            fake_services = FakeServices()
            fake_terminal = FakeTerminalPort()
            fake_terminal_adapter = FakeTerminalAdapter()
            ClientApp = client.client_app_class(self.make_dependencies(Path(tmpdir)))

            with (
                patch.object(ClientApp, "app_state_controller", return_value=fake_state),
                patch.object(ClientApp, "app_services_controller", return_value=fake_services),
                patch.object(ClientApp, "terminal_port_controller", return_value=fake_terminal),
                patch.object(ClientApp, "terminal_port_adapter", return_value=fake_terminal_adapter),
            ):
                app = ClientApp(FakeScreen(), {})

            app.load_active_project_runtime()
            app.refresh_mapping_selection_cache()
            app.reload_config_from_disk()
            app.ui_profile("event", value="x")
            self.assertEqual(app.ui_profile_slow("slow", 1.0), 12.5)
            app.flush_ui_profile()
            app.run()
            app.handle_main_key(10)
            app.draw()
            self.assertEqual(app.stop_running_preview("build"), "preview:build")
            self.assertEqual(app.selected_attr(), 7)
            self.assertEqual(app.read_key(), 113)
            app.add(1, 2, "text", 3)
            app.quit()

            self.assertEqual(app.config, {"reloaded": True})
            self.assertEqual(fake_state.runtime_calls, [app, app])
            self.assertEqual(fake_state.refresh_calls, [app, app])
            self.assertEqual(fake_state.profile_calls, [(app, "event", {"value": "x"})])
            self.assertTrue(app.flushed)
            self.assertEqual(fake_services.calls[-3:], [("run", app, None), ("key", app, 10), ("draw", app, None)])
            self.assertEqual(app.added, (1, 2, "text", 3))
            self.assertEqual(fake_state.quit_calls, [app])


if __name__ == "__main__":
    unittest.main()
