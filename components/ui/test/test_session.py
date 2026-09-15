from __future__ import annotations

import unittest

from components.ui.api import session


class Target:
    pass


class App:
    def __init__(self, screen: object, config: dict[str, object]) -> None:
        self.screen = screen
        self.config = config

    def run(self) -> tuple[object, dict[str, object]]:
        return self.screen, self.config


class SessionBehaviorTests(unittest.TestCase):
    def test_apply_state_sets_attributes_from_state_dict(self) -> None:
        target = Target()

        session.apply_state(target, {"status": "Running", "logs_dirty": True})

        self.assertEqual(target.status, "Running")
        self.assertTrue(target.logs_dirty)

    def test_reset_preflight_matches_client_state_reset(self) -> None:
        target = Target()
        target.preflight = "ok"
        target.preflight_values = {"docker": "ok"}
        target.menu_dirty = False
        target.render_cache = {"header": "cached", "body": "cached"}

        session.reset_preflight(target)

        self.assertEqual(target.preflight, "not run")
        self.assertEqual(target.preflight_values, {})
        self.assertTrue(target.menu_dirty)
        self.assertEqual(target.render_cache, {"body": "cached"})

    def test_run_curses_app_delegates_to_wrapper_and_app_factory(self) -> None:
        config = {"name": "prod"}

        def wrapper(callback):
            return callback("screen")

        self.assertEqual(
            session.run_curses_app(config, app_factory=App, wrapper=wrapper),
            ("screen", config),
        )

    def test_connection_label_matches_current_states(self) -> None:
        self.assertEqual(session.connection_label("connected"), "Disconnect")
        self.assertEqual(session.connection_label("connecting"), "Connecting...")
        self.assertEqual(session.connection_label("disconnecting"), "Disconnecting...")
        self.assertEqual(session.connection_label("disconnected"), "Connect")
        self.assertEqual(session.connection_label("unknown"), "Connect")

    def test_connection_menu_label_uses_host_connection_state(self) -> None:
        self.assertEqual(
            session.connection_menu_label("Connect build host", build_state="connected", board_state="disconnected"),
            "Disconnect build host",
        )
        self.assertEqual(
            session.connection_menu_label("Connect board host", build_state="connected", board_state="connecting"),
            "Connecting... board host",
        )
        self.assertEqual(
            session.connection_menu_label("Run product build", build_state="connected", board_state="connected"),
            "Run product build",
        )

    def test_build_host_toggle_guard_matches_current_status_policy(self) -> None:
        self.assertEqual(
            session.build_host_toggle_guard(
                action_running=True,
                active_job_exists=False,
                connected=False,
                remote_has_user=True,
                remote_has_host=True,
            ),
            {"allowed": False, "status": "Another action is already running"},
        )
        self.assertEqual(
            session.build_host_toggle_guard(
                action_running=False,
                active_job_exists=True,
                connected=False,
                remote_has_user=True,
                remote_has_host=True,
            ),
            {"allowed": False, "status": "Another command is already running"},
        )
        self.assertEqual(
            session.build_host_toggle_guard(
                action_running=False,
                active_job_exists=False,
                connected=False,
                remote_has_user=False,
                remote_has_host=True,
            ),
            {"allowed": False, "status": "set SSH user first"},
        )
        self.assertEqual(
            session.build_host_toggle_guard(
                action_running=False,
                active_job_exists=False,
                connected=False,
                remote_has_user=True,
                remote_has_host=False,
            ),
            {"allowed": False, "status": "set SSH host first"},
        )
        self.assertEqual(
            session.build_host_toggle_guard(
                action_running=False,
                active_job_exists=False,
                connected=True,
                remote_has_user=True,
                remote_has_host=True,
            ),
            {"allowed": True, "status": ""},
        )

    def test_build_host_toggle_plan_matches_current_policy(self) -> None:
        self.assertEqual(
            session.build_host_toggle_plan(
                action_running=True,
                active_job_exists=False,
                connected=False,
                remote_has_user=True,
                remote_has_host=True,
                remote_label="Build",
                remote_spec="user@host",
            ),
            {"action": "status", "status": "Another action is already running"},
        )
        self.assertEqual(
            session.build_host_toggle_plan(
                action_running=False,
                active_job_exists=False,
                connected=False,
                remote_has_user=True,
                remote_has_host=True,
                remote_label="Build",
                remote_spec="user@host",
            ),
            {"action": "start_connect"},
        )
        self.assertEqual(
            session.build_host_toggle_plan(
                action_running=False,
                active_job_exists=False,
                connected=True,
                remote_has_user=True,
                remote_has_host=True,
                remote_label="Build",
                remote_spec="user@host",
            ),
            {
                "action": "confirm_disconnect",
                "confirm_title": "Disconnect",
                "confirm_subject": "Build  user@host",
                "cancel_status": "Cancelled: Disconnect",
                "start_state": {"connection_state": "disconnecting", "status": "Disconnecting..."},
                "done_state": {"connection_state": "disconnected", "status": "Disconnected"},
            },
        )

    def test_board_host_toggle_guard_matches_current_status_policy(self) -> None:
        self.assertEqual(
            session.board_host_toggle_guard(
                action_running=False,
                board_job_exists=True,
                connected=False,
                board_has_user=True,
                board_has_host=True,
            ),
            {"allowed": False, "status": "Another board command is already running"},
        )
        self.assertEqual(
            session.board_host_toggle_guard(
                action_running=False,
                board_job_exists=False,
                connected=False,
                board_has_user=False,
                board_has_host=True,
            ),
            {"allowed": False, "status": "set board SSH user first"},
        )
        self.assertEqual(
            session.board_host_toggle_guard(
                action_running=False,
                board_job_exists=False,
                connected=False,
                board_has_user=True,
                board_has_host=False,
            ),
            {"allowed": False, "status": "set board SSH host first"},
        )
        self.assertEqual(
            session.board_host_toggle_guard(
                action_running=False,
                board_job_exists=False,
                connected=True,
                board_has_user=True,
                board_has_host=True,
            ),
            {"allowed": True, "status": ""},
        )

    def test_board_host_toggle_plan_matches_current_policy(self) -> None:
        self.assertEqual(
            session.board_host_toggle_plan(
                action_running=True,
                board_job_exists=False,
                connected=False,
                board_has_user=True,
                board_has_host=True,
                board_label="Board",
                board_spec="board@host",
            ),
            {"action": "status", "status": "Another action is already running"},
        )
        self.assertEqual(
            session.board_host_toggle_plan(
                action_running=False,
                board_job_exists=False,
                connected=False,
                board_has_user=True,
                board_has_host=True,
                board_label="Board",
                board_spec="board@host",
            ),
            {"action": "start_connect"},
        )
        self.assertEqual(
            session.board_host_toggle_plan(
                action_running=False,
                board_job_exists=False,
                connected=True,
                board_has_user=True,
                board_has_host=True,
                board_label="Board",
                board_spec="board@host",
            ),
            {
                "action": "confirm_disconnect",
                "confirm_title": "Disconnect board host",
                "confirm_subject": "Board  board@host",
                "cancel_status": "Cancelled: Disconnect board host",
                "start_state": {"board_connection_state": "disconnecting", "status": "Disconnecting board host..."},
                "done_state": {"board_connection_state": "disconnected", "status": "Board host disconnected"},
            },
        )

    def test_connection_state_helpers_match_current_toggle_text(self) -> None:
        self.assertEqual(
            session.build_host_disconnect_start_state(),
            {"connection_state": "disconnecting", "status": "Disconnecting..."},
        )
        self.assertEqual(
            session.build_host_disconnected_state(),
            {"connection_state": "disconnected", "status": "Disconnected"},
        )
        self.assertEqual(
            session.board_host_disconnect_start_state(),
            {"board_connection_state": "disconnecting", "status": "Disconnecting board host..."},
        )
        self.assertEqual(
            session.board_host_disconnected_state(),
            {"board_connection_state": "disconnected", "status": "Board host disconnected"},
        )
        self.assertEqual(
            session.build_host_connect_start_state(),
            {"connection_state": "connecting", "preflight": "checking...", "status": "Connecting..."},
        )
        self.assertEqual(
            session.board_host_connect_start_state(),
            {"board_connection_state": "connecting", "status": "Connecting board host..."},
        )
        self.assertEqual(
            session.connect_job_started_state(),
            {
                "focus_panel": "actions",
                "menu_dirty": True,
                "main_full_redraw": True,
                "logs_dirty": True,
            },
        )

    def test_auto_connect_plan_matches_current_startup_policy(self) -> None:
        self.assertEqual(session.auto_connect_plan(auto_connect_done=True, board_has_ssh=True, remote_has_ssh=True), {"action": "noop"})
        self.assertEqual(
            session.auto_connect_plan(auto_connect_done=False, board_has_ssh=True, remote_has_ssh=True),
            {
                "action": "start_build",
                "state": {"auto_connect_done": True, "pending_auto_board_connect": True},
            },
        )
        self.assertEqual(
            session.auto_connect_plan(auto_connect_done=False, board_has_ssh=True, remote_has_ssh=False),
            {
                "action": "start_board",
                "state": {"auto_connect_done": True, "pending_auto_board_connect": False},
            },
        )
        self.assertEqual(
            session.auto_connect_plan(auto_connect_done=False, board_has_ssh=False, remote_has_ssh=False),
            {
                "action": "status",
                "state": {
                    "auto_connect_done": True,
                    "pending_auto_board_connect": False,
                    "status": "Build and board SSH user/host are not configured",
                },
            },
        )

    def test_pending_board_connect_plan_matches_current_policy(self) -> None:
        self.assertEqual(
            session.pending_board_connect_plan(
                pending_auto_board_connect=False,
                action_running=False,
                board_job_exists=False,
                board_has_ssh=True,
                board_connected=False,
            ),
            {"action": "noop"},
        )
        self.assertEqual(
            session.pending_board_connect_plan(
                pending_auto_board_connect=True,
                action_running=True,
                board_job_exists=False,
                board_has_ssh=True,
                board_connected=False,
            ),
            {"action": "clear", "state": {"pending_auto_board_connect": False}},
        )
        self.assertEqual(
            session.pending_board_connect_plan(
                pending_auto_board_connect=True,
                action_running=False,
                board_job_exists=False,
                board_has_ssh=True,
                board_connected=False,
            ),
            {"action": "start_board", "state": {"pending_auto_board_connect": False}},
        )

    def test_build_host_connection_preview_matches_current_text(self) -> None:
        command = ["ssh", "-o", "BatchMode=yes", "builder@host", "printf ok"]

        self.assertEqual(
            session.build_host_connection_preview("connected", command),
            "disconnect from Moulin client build host session",
        )
        self.assertEqual(
            session.build_host_connection_preview("connecting", command),
            "checking SSH access to the build host",
        )
        self.assertEqual(
            session.build_host_connection_preview("disconnecting", command),
            "clearing local connection state",
        )
        self.assertEqual(
            session.build_host_connection_preview("disconnected", command),
            "ssh -o BatchMode=yes builder@host 'printf ok'",
        )

    def test_board_host_connection_preview_matches_current_text(self) -> None:
        command = ["ssh", "-o", "BatchMode=yes", "board@host", "printf ok"]

        self.assertEqual(
            session.board_host_connection_preview("connected", command),
            "disconnect from Moulin client board host session",
        )
        self.assertEqual(
            session.board_host_connection_preview("connecting", command),
            "checking SSH access to the board host",
        )
        self.assertEqual(
            session.board_host_connection_preview("disconnecting", command),
            "clearing board connection state",
        )
        self.assertEqual(
            session.board_host_connection_preview("disconnected", command),
            "ssh -o BatchMode=yes board@host 'printf ok'",
        )


if __name__ == "__main__":
    unittest.main()
