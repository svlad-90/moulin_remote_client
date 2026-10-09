"""Main TUI run loop workflow."""

from __future__ import annotations

import time
from typing import Any, Callable

from components.jobs.api import jobs as job_api


class MainRunLoopController:
    """Run the main TUI event loop."""

    def __init__(
        self,
        *,
        auto_connect_enabled: bool,
        sleep: Callable[[float], Any] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.auto_connect_enabled = auto_connect_enabled
        self.sleep = sleep
        self.monotonic = monotonic

    def run(self, port: Any) -> None:
        port.configure_escape_delay()
        port.configure_mouse()
        port.set_cursor(False)
        port.screen.keypad(True)
        port.screen.timeout(250)
        started = self.monotonic()
        port.draw()
        port.ui_profile_slow("draw-initial", started)
        auto_connect_pending = self.auto_connect_enabled
        try:
            while not port.done:
                self._poll_jobs(port)
                input_timeout = 0.05 if job_api.has_active_job(port.active_job, port.board_job) else 0.25
                port.screen.timeout(max(0, int(input_timeout * 1000)))
                wait_started = self.monotonic()
                ch = port.read_key()
                if auto_connect_pending and ch == -1:
                    auto_connect_pending = False
                    self._start_auto_connect(port)
                    self.sleep(0.05)
                    continue
                if ch == -1:
                    port.ui_profile_slow(
                        "input-wait-timeout",
                        wait_started,
                        threshold_ms=300.0,
                        active=job_api.has_active_job(port.active_job, port.board_job),
                    )
                    started = self.monotonic()
                    port.draw()
                    port.ui_profile_slow("draw-idle-slow", started)
                    self.sleep(0.05)
                    continue
                self._handle_input(port, ch)
                if auto_connect_pending and not port.done:
                    auto_connect_pending = False
                    self._start_auto_connect(port)
        finally:
            port.flush_ui_profile()

    def _start_auto_connect(self, port: Any) -> None:
        started = self.monotonic()
        port.connection_workflow_service().auto_connect(port)
        port.ui_profile_slow("auto-connect-start-slow", started, threshold_ms=20.0)
        started = self.monotonic()
        port.draw()
        port.ui_profile_slow("draw-auto-connect-slow", started)

    def _poll_jobs(self, port: Any) -> None:
        started = self.monotonic()
        port.poll_active_jobs()
        port.ui_profile_slow("poll-slow", started)

    def _handle_input(self, port: Any, ch: int) -> None:
        batch_started = self.monotonic()
        key_started = self.monotonic()
        port.handle_main_key(ch)
        port.ui_profile_slow(
            "key-handler-slow",
            key_started,
            threshold_ms=5.0,
            key=ch,
            selected=port.selected,
            active=job_api.has_active_job(port.active_job, port.board_job),
        )
        port.ui_profile_slow(
            "input-batch-slow",
            batch_started,
            threshold_ms=10.0,
            keys=1,
            selected=port.selected,
            active=job_api.has_active_job(port.active_job, port.board_job),
        )
        started = self.monotonic()
        port.draw()
        port.ui_profile_slow("draw-after-input-slow", started)


def main_run_loop_controller(
    *,
    auto_connect_enabled: bool,
    sleep: Callable[[float], Any] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> MainRunLoopController:
    return MainRunLoopController(
        auto_connect_enabled=auto_connect_enabled,
        sleep=sleep,
        monotonic=monotonic,
    )
