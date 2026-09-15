from __future__ import annotations

import unittest
import os
import sys
from collections import deque
from typing import Any

from components.jobs.api import jobs


class FakeProcess:
    def __init__(self, rc: int | None, *, pid: int = 1234) -> None:
        self.rc = rc
        self.pid = pid

    def poll(self) -> int | None:
        return self.rc


class FakeReader:
    def __init__(self, alive: bool) -> None:
        self.alive = alive
        self.join_timeout: float | None = None

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        self.join_timeout = timeout


class FakeStreamProcess:
    def __init__(self, fd: int) -> None:
        self.stdout = os.fdopen(fd, "rb", closefd=True)


class JobsBehaviorTests(unittest.TestCase):
    def test_create_command_job_preserves_current_shape(self) -> None:
        commands = [["echo", "ok"]]

        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot=None,
            commands=commands,
        )

        self.assertEqual(job["title"], "Build")
        self.assertEqual(job["item_label"], "Run product build")
        self.assertEqual(job["slot"], "build")
        self.assertIs(job["commands"], commands)
        self.assertEqual(job["index"], 0)
        self.assertIsInstance(job["output"], deque)
        self.assertEqual(job["output"].maxlen, 1000)
        self.assertIsNone(job["process"])
        self.assertEqual(job["current_command"], "")
        self.assertIsNone(job["rc"])
        self.assertFalse(job["finished"])
        self.assertTrue(hasattr(job["output_lock"], "acquire"))

    def test_create_command_job_supports_connect_metadata(self) -> None:
        job = jobs.create_command_job(
            kind="connect",
            title="Connect to build host",
            item_label="Connect build host",
            slot="build",
            commands=[["ssh", "host", "true"]],
            initial_output=["Starting remote preflight..."],
            started_at=12.5,
            timeout=10.0,
        )

        self.assertEqual(job["kind"], "connect")
        self.assertEqual(list(job["output"]), ["Starting remote preflight..."])
        self.assertEqual(job["started_at"], 12.5)
        self.assertEqual(job["timeout"], 10.0)

    def test_connect_job_factories_preserve_current_shape(self) -> None:
        build = jobs.create_build_connect_job(
            item_label="Connect build host",
            command=["ssh", "builder", "true"],
            started_at=12.5,
        )
        board = jobs.create_board_connect_job(
            item_label="Connect board host",
            command=["ssh", "board", "true"],
            started_at=13.5,
        )

        self.assertEqual(build["kind"], "connect")
        self.assertEqual(build["title"], "Connect to build host")
        self.assertEqual(build["item_label"], "Connect build host")
        self.assertEqual(build["slot"], "build")
        self.assertEqual(build["commands"], [["ssh", "builder", "true"]])
        self.assertEqual(list(build["output"]), ["Starting remote preflight..."])
        self.assertEqual(build["started_at"], 12.5)
        self.assertEqual(build["timeout"], 10.0)

        self.assertEqual(board["kind"], "board-connect")
        self.assertEqual(board["title"], "Connect to board host")
        self.assertEqual(board["item_label"], "Connect board host")
        self.assertEqual(board["slot"], "board")
        self.assertEqual(board["commands"], [["ssh", "board", "true"]])
        self.assertEqual(list(board["output"]), ["Starting board host SSH check..."])
        self.assertEqual(board["started_at"], 13.5)
        self.assertEqual(board["timeout"], 10.0)

    def test_job_running_tracks_active_sequence_until_finished(self) -> None:
        running = {"process": FakeProcess(None)}
        between_steps = {"process": FakeProcess(0)}
        finished = {"process": FakeProcess(0), "finished": True}

        self.assertTrue(jobs.job_running(running))
        self.assertTrue(jobs.job_running(between_steps))
        self.assertFalse(jobs.job_running(finished))
        self.assertFalse(jobs.job_running(None))

    def test_process_helpers_use_duck_typed_process_contract(self) -> None:
        running = FakeProcess(None, pid=42)
        stopped = FakeProcess(7, pid=43)

        self.assertTrue(jobs.process_running(running))
        self.assertFalse(jobs.process_running(stopped))
        self.assertFalse(jobs.process_running(object()))
        self.assertIsNone(jobs.process_returncode(running))
        self.assertEqual(jobs.process_returncode(stopped), 7)
        self.assertEqual(jobs.process_pid(running), 42)
        self.assertIsNone(jobs.process_pid(object()))

    def test_join_output_reader_joins_only_live_reader(self) -> None:
        live = FakeReader(True)
        stopped = FakeReader(False)

        jobs.join_output_reader({"output_reader": live}, timeout=0.5)
        jobs.join_output_reader({"output_reader": stopped}, timeout=0.5)
        jobs.join_output_reader({}, timeout=0.5)

        self.assertEqual(live.join_timeout, 0.5)
        self.assertIsNone(stopped.join_timeout)

    def test_running_job_list_and_active_job_flag_use_build_and_board_jobs(self) -> None:
        build = {"title": "Build"}
        board = {"title": "Flash"}

        self.assertFalse(jobs.has_active_job(None, None))
        self.assertTrue(jobs.has_active_job(build, None))
        self.assertTrue(jobs.has_active_job(None, board))
        self.assertEqual(jobs.running_job_list(build, board), [build, board])
        self.assertEqual(jobs.running_job_list(None, board), [board])

    def test_any_job_running_uses_job_state(self) -> None:
        self.assertFalse(jobs.any_job_running([]))
        self.assertFalse(jobs.any_job_running([{"process": FakeProcess(0), "finished": True}]))
        self.assertTrue(jobs.any_job_running([{"process": FakeProcess(0)}, {"process": FakeProcess(None)}]))

    def test_stop_running_preview_matches_current_messages(self) -> None:
        self.assertEqual(jobs.stop_running_preview(None, None), "No command is running.")
        self.assertEqual(jobs.stop_running_preview(None, "build"), "No build or sync command is running.")
        self.assertEqual(jobs.stop_running_preview(None, "board"), "No board command is running.")
        self.assertEqual(jobs.stop_running_preview({"title": "Flash UFS image"}, "board"), "Stop active command: Flash UFS image")

    def test_request_stop_plan_preserves_stop_job_status_paths(self) -> None:
        self.assertEqual(
            jobs.request_stop_plan(None, "board", process_running=False, now=12.0),
            {"action": "status", "status": "No board command is running"},
        )
        self.assertEqual(
            jobs.request_stop_plan({"stopping": True}, "build", process_running=True, now=12.0),
            {"action": "status", "status": "Command stop is already requested"},
        )

    def test_request_stop_plan_marks_running_process_for_sigterm(self) -> None:
        job = {"title": "Build"}

        self.assertEqual(
            jobs.request_stop_plan(job, "build", process_running=True, now=12.0),
            {
                "action": "terminate",
                "log": "stop requested: SIGTERM",
                "status": "Stop requested",
                "logs_dirty": True,
            },
        )
        self.assertTrue(job["stopping"])
        self.assertEqual(job["stop_requested_at"], 12.0)

    def test_request_stop_plan_finishes_job_without_active_process(self) -> None:
        job = {"title": "Build"}

        self.assertEqual(
            jobs.request_stop_plan(job, "build", process_running=False, now=12.0),
            {
                "action": "finish",
                "log": "stopped: no active process",
                "state": {"last_exit": 130, "status": "Build: stopped"},
            },
        )
        self.assertTrue(job["stopping"])
        self.assertEqual(job["rc"], 130)

    def test_no_running_command_message_can_omit_punctuation_for_status(self) -> None:
        self.assertEqual(jobs.no_running_command_message(None, punctuation=False), "No command is running")
        self.assertEqual(jobs.no_running_command_message("build", punctuation=False), "No build or sync command is running")
        self.assertEqual(jobs.no_running_command_message("board", punctuation=False), "No board command is running")

    def test_log_visible_lines_matches_client_method(self) -> None:
        self.assertEqual(jobs.log_visible_lines(40, expanded=False), 7)
        self.assertEqual(jobs.log_visible_lines(40, expanded=True), 34)

    def test_log_scroll_plan_matches_current_client_scroll_behavior(self) -> None:
        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot="build",
            commands=[],
            initial_output=["1", "2", "3", "4"],
        )

        self.assertEqual(jobs.log_scroll_plan(None, 2, follow=True, scroll=0, delta=1), {"status": "No log for selected action"})
        self.assertEqual(jobs.log_scroll_plan(job, 2, follow=True, scroll=0, delta=-1), {"log_scroll": 1, "log_follow": False})
        self.assertEqual(jobs.log_scroll_plan(job, 2, follow=False, scroll=0, delta=1), {"log_scroll": 1, "log_follow": False})
        self.assertEqual(jobs.log_scroll_plan(job, 2, follow=False, scroll=1, delta=1), {"log_scroll": 2, "log_follow": True})

    def test_job_output_lines_copies_locked_output(self) -> None:
        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot="build",
            commands=[],
            initial_output=["one", "two"],
        )

        lines = jobs.job_output_lines(job)

        self.assertEqual(lines, ["one", "two"])
        self.assertIsNot(lines, job["output"])
        self.assertEqual(jobs.job_output_lines(None), [])

    def test_append_job_output_sanitizes_splits_and_collapses_blank_lines(self) -> None:
        job = jobs.create_command_job(title="Build", item_label="Run product build", slot="build", commands=[])

        jobs.append_job_output(job, "\x1b[31mred\x1b[0m\r\n\n\nok\x07")

        self.assertEqual(jobs.job_output_lines(job), ["red", "", "ok "])
        self.assertTrue(job["last_log_line_blank"] is False)

    def test_append_job_output_stream_updates_live_partial_line(self) -> None:
        job = jobs.create_command_job(title="Build", item_label="Run product build", slot="build", commands=[])

        jobs.append_job_output_stream(job, "abc")
        self.assertEqual(jobs.job_output_lines(job), ["abc"])
        self.assertEqual(job["partial_output"], "abc")
        self.assertTrue(job["partial_live"])

        jobs.append_job_output_stream(job, "def\nnext")
        self.assertEqual(jobs.job_output_lines(job), ["abcdef", "next"])
        self.assertEqual(job["partial_output"], "next")
        self.assertTrue(job["partial_live"])

    def test_append_job_output_stream_rolls_long_live_line(self) -> None:
        job = jobs.create_command_job(title="Build", item_label="Run product build", slot="build", commands=[])

        jobs.append_job_output_stream(job, "x" * 121)

        self.assertEqual(jobs.job_output_lines(job), ["x" * 121])
        self.assertEqual(job["partial_output"], "x" * 121)
        self.assertTrue(job["partial_live"])

    def test_read_process_output_stream_appends_chunks_and_marks_dirty(self) -> None:
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"abc\nnext")
        os.close(write_fd)
        job = jobs.create_command_job(title="Build", item_label="Run product build", slot="build", commands=[])
        dirty_count = 0

        def mark_dirty() -> None:
            nonlocal dirty_count
            dirty_count += 1

        jobs.read_process_output_stream(FakeStreamProcess(read_fd), job, mark_dirty)

        self.assertEqual(jobs.job_output_lines(job), ["abc", "next"])
        self.assertGreaterEqual(dirty_count, 1)

    def test_start_command_process_attaches_process_and_reader(self) -> None:
        job = jobs.create_command_job(title="Build", item_label="Run product build", slot="build", commands=[])
        dirty_count = 0

        def mark_dirty() -> None:
            nonlocal dirty_count
            dirty_count += 1

        process = jobs.start_command_process(
            job,
            [sys.executable, "-c", "print('hello')"],
            mark_dirty,
        )
        self.assertIs(job["process"], process)
        job["output_reader"].join(timeout=2.0)
        rc = process.wait(timeout=2.0)

        self.assertEqual(rc, 0)
        self.assertEqual(jobs.job_output_lines(job), ["hello"])
        self.assertGreaterEqual(dirty_count, 1)

    def test_log_scroll_helpers_match_client_methods(self) -> None:
        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot="build",
            commands=[],
            initial_output=[str(index) for index in range(10)],
        )
        self.assertEqual(jobs.log_max_scroll(job, 4), 6)
        self.assertEqual(jobs.clamp_log_scroll(job, 4, follow=True, scroll=0), (6, True))
        self.assertEqual(jobs.clamp_log_scroll(job, 4, follow=False, scroll=99), (6, False))

    def test_display_job_for_label_prefers_active_then_last_jobs(self) -> None:
        active = {"item_label": "Current"}
        last_board = {"item_label": "Flash UFS image"}
        last_build = {"item_label": "Run product build"}

        self.assertIs(jobs.display_job_for_label("Any", active, last_board, last_build), active)
        self.assertIs(jobs.display_job_for_label("Flash UFS image", None, last_board, last_build), last_board)
        self.assertIs(jobs.display_job_for_label("Run product build", None, last_board, last_build), last_build)
        self.assertIsNone(jobs.display_job_for_label("Other", None, last_board, last_build))

    def test_selected_or_first_running_job_matches_stop_selection_order(self) -> None:
        active = {"item_label": "Run product build"}
        board = {"item_label": "Flash UFS image"}
        selected = {"item_label": "Regenerate Moulin/Ninja"}

        self.assertIs(jobs.active_job_for_slot("build", active_job=active, board_job=board), active)
        self.assertIs(jobs.active_job_for_slot("board", active_job=active, board_job=board), board)
        self.assertIsNone(jobs.active_job_for_slot(None, active_job=active, board_job=board))
        self.assertIs(
            jobs.selected_or_first_running_job(slot="build", active_job=active, board_job=board, selected_job=selected),
            active,
        )
        self.assertIs(
            jobs.selected_or_first_running_job(slot="board", active_job=active, board_job=board, selected_job=selected),
            board,
        )
        self.assertIs(
            jobs.selected_or_first_running_job(slot=None, active_job=active, board_job=board, selected_job=selected),
            selected,
        )
        self.assertIs(
            jobs.selected_or_first_running_job(slot=None, active_job=active, board_job=board, selected_job=None),
            active,
        )
        self.assertIsNone(
            jobs.selected_or_first_running_job(slot=None, active_job=None, board_job=None, selected_job=None),
        )

    def test_selected_or_first_running_job_for_label_uses_selected_item_label(self) -> None:
        active = {"title": "Run product build", "item_label": "Run product build"}
        board = {"title": "Flash UFS image", "item_label": "Flash UFS image"}

        self.assertIs(
            jobs.selected_or_first_running_job_for_label(
                slot=None,
                active_job=active,
                board_job=board,
                selected_item_label="Flash UFS image",
            ),
            board,
        )
        self.assertIs(
            jobs.selected_or_first_running_job_for_label(
                slot=None,
                active_job=active,
                board_job=board,
                selected_item_label="Other",
            ),
            active,
        )
        self.assertEqual(
            jobs.stop_running_preview_for_label(
                slot=None,
                active_job=active,
                board_job=board,
                selected_item_label="Flash UFS image",
            ),
            "Stop active command: Flash UFS image",
        )

    def test_command_started_state_matches_current_run_commands_policy(self) -> None:
        self.assertEqual(
            jobs.command_started_state("Run product build"),
            {
                "status": "Running: Run product build",
                "focus_panel": "actions",
                "menu_dirty": True,
                "main_full_redraw": True,
                "logs_dirty": True,
            },
        )

    def test_build_command_start_plan_preserves_current_conflict_policy(self) -> None:
        self.assertEqual(
            jobs.build_command_start_plan(
                title="Build",
                item_label="Run product build",
                slot="build",
                commands=[["ninja"]],
                action_running=True,
                active_job=None,
                board_job=None,
            ),
            {"rc": 1, "status": "Another action is already running"},
        )
        self.assertEqual(
            jobs.build_command_start_plan(
                title="Build",
                item_label="Run product build",
                slot="build",
                commands=[["ninja"]],
                action_running=False,
                active_job={"title": "Existing"},
                board_job=None,
            ),
            {"rc": 1, "status": "Another build action is already running"},
        )
        self.assertEqual(
            jobs.build_command_start_plan(
                title="Flash",
                item_label="Flash UFS image",
                slot="board",
                commands=[["flash"]],
                action_running=False,
                active_job=None,
                board_job={"title": "Existing"},
            ),
            {"rc": 1, "status": "Another board action is already running"},
        )

    def test_build_command_start_plan_creates_target_slot_job_and_started_state(self) -> None:
        plan = jobs.build_command_start_plan(
            title="Flash",
            item_label="Flash UFS image",
            slot="board",
            commands=[["flash"]],
            action_running=False,
            active_job=None,
            board_job=None,
        )

        self.assertEqual(plan["rc"], 0)
        self.assertEqual(plan["slot"], "board")
        self.assertEqual(plan["job"]["title"], "Flash")
        self.assertEqual(plan["job"]["item_label"], "Flash UFS image")
        self.assertEqual(plan["job"]["commands"], [["flash"]])
        self.assertEqual(plan["state"], jobs.command_started_state("Flash"))

    def test_finish_job_state_moves_running_job_to_last_slot(self) -> None:
        active = {"title": "Build"}
        board = {"title": "Flash"}

        self.assertEqual(
            jobs.finish_job_state(active, active_job=active, board_job=board),
            {
                "last_job": active,
                "active_job": None,
                "menu_dirty": True,
                "main_full_redraw": True,
                "logs_dirty": True,
            },
        )
        self.assertEqual(
            jobs.finish_job_state(board, active_job=active, board_job=board),
            {
                "last_board_job": board,
                "board_job": None,
                "menu_dirty": True,
                "main_full_redraw": True,
                "logs_dirty": True,
            },
        )
        self.assertEqual(jobs.finish_job_state({"title": "other"}, active_job=active, board_job=board), {})

    def test_next_command_step_plan_starts_current_command_or_completes_sequence(self) -> None:
        job = {"title": "Build", "commands": [["one"], ["two"]], "index": 1, "rc": 0}

        self.assertEqual(
            jobs.next_command_step_plan(job),
            {"action": "start", "command": ["two"], "index": 1, "total": 2},
        )

        job["index"] = 2
        self.assertEqual(
            jobs.next_command_step_plan(job),
            {
                "action": "complete",
                "state": {"last_exit": 0, "status": "Build: exit 0"},
            },
        )

    def test_record_command_step_start_sets_current_command_and_log_lines(self) -> None:
        job: dict[str, Any] = {}

        self.assertEqual(
            jobs.record_command_step_start(
                job,
                index=1,
                total=3,
                current_command="ssh host '<script>'",
                command_lines=["command: ssh host '<script>'", "script:", "  ninja"],
            ),
            ["Starting step 2/3...", "command: ssh host '<script>'", "script:", "  ninja"],
        )
        self.assertEqual(job["current_command"], "ssh host '<script>'")

    def test_prepare_command_step_start_moves_client_display_policy_into_jobs(self) -> None:
        job: dict[str, Any] = {}
        plan = {"command": ["ssh", "host", "echo ok"], "index": 0, "total": 2}

        result = jobs.prepare_command_step_start(
            job,
            plan,
            display_command=lambda command: " ".join(command),
            display_command_lines=lambda command: ["command: " + " ".join(command)],
        )

        self.assertEqual(
            result,
            {
                "command": ["ssh", "host", "echo ok"],
                "log_lines": ["Starting step 1/2...", "command: ssh host echo ok"],
            },
        )
        self.assertEqual(job["current_command"], "ssh host echo ok")

    def test_advance_completed_command_step_matches_client_advance_branch(self) -> None:
        job: dict[str, Any] = {"index": 1, "process": object()}

        jobs.advance_completed_command_step(job)

        self.assertEqual(job["index"], 2)
        self.assertIsNone(job["process"])

    def test_completed_command_sequence_state_matches_current_status_policy(self) -> None:
        self.assertEqual(
            jobs.completed_command_sequence_state({"title": "Run product build", "rc": 0}),
            {"last_exit": 0, "status": "Run product build: exit 0"},
        )
        self.assertEqual(
            jobs.completed_command_sequence_state({"title": "Prepare remote project", "rc": 0}),
            {
                "last_exit": 0,
                "status": "Prepare remote project: done; reconnect to refresh preflight",
                "needs_preflight_reset": True,
            },
        )

    def test_timeout_predicates_match_current_poll_policy(self) -> None:
        self.assertTrue(jobs.stop_timeout_due({"stopping": True, "stop_requested_at": 10.0}, 12.1))
        self.assertFalse(jobs.stop_timeout_due({"stopping": True, "stop_requested_at": 10.0}, 11.0))
        self.assertFalse(jobs.stop_timeout_due({"stop_requested_at": 10.0}, 12.1))

        self.assertTrue(jobs.connect_timeout_due({"kind": "connect", "started_at": 10.0, "timeout": 2.0}, 12.1))
        self.assertTrue(jobs.connect_timeout_due({"kind": "board-connect", "started_at": 10.0}, 20.1))
        self.assertFalse(jobs.connect_timeout_due({"kind": "build", "started_at": 10.0, "timeout": 2.0}, 20.0))

    def test_poll_process_plan_matches_current_poll_branches(self) -> None:
        self.assertEqual(
            jobs.poll_process_plan({"process": None}, process_running=False, rc=None, now=12.0),
            {"action": "start_next"},
        )
        self.assertEqual(
            jobs.poll_process_plan(
                {"process": object(), "stopping": True, "stop_requested_at": 10.0},
                process_running=True,
                rc=None,
                now=12.1,
            ),
            {"action": "stop_timeout", "log": "stop timeout: SIGKILL"},
        )
        self.assertEqual(
            jobs.poll_process_plan(
                {"process": object(), "kind": "connect", "started_at": 10.0, "timeout": 2.0},
                process_running=True,
                rc=None,
                now=12.1,
            ),
            {
                "action": "connect_timeout",
                "log": "timeout",
                "state": jobs.connect_timeout_state("connect"),
                "start_pending_auto_board_connect": True,
            },
        )
        self.assertEqual(
            jobs.poll_process_plan({"process": object()}, process_running=True, rc=None, now=12.0),
            {"action": "wait"},
        )
        completed_job = {"process": object(), "title": "Build"}
        self.assertEqual(
            jobs.poll_process_plan(completed_job, process_running=False, rc=0, now=12.0),
            {
                "action": "process_complete",
                "log": "exit: 0",
                "completed": {"action": "advance", "state": {}},
            },
        )
        self.assertEqual(completed_job["rc"], 0)

    def test_connection_lifecycle_states_match_current_status_text(self) -> None:
        self.assertEqual(
            jobs.connect_timeout_state("connect"),
            {
                "last_exit": 124,
                "preflight": "timeout",
                "preflight_values": {},
                "connection_state": "disconnected",
                "status": "Disconnected: connect timeout",
            },
        )
        self.assertEqual(
            jobs.connect_timeout_state("board-connect"),
            {
                "last_exit": 124,
                "board_connection_state": "disconnected",
                "status": "Board host disconnected: connect timeout",
            },
        )
        self.assertEqual(jobs.connect_completed_state(0), {"last_exit": 0, "connection_state": "connected", "status": "Connected"})
        self.assertEqual(
            jobs.connect_completed_state(1),
            {"last_exit": 1, "connection_state": "disconnected", "status": "Disconnected: connect failed"},
        )
        self.assertEqual(
            jobs.board_connect_completed_state(0),
            {"last_exit": 0, "board_connection_state": "connected", "status": "Board host connected"},
        )
        self.assertEqual(
            jobs.board_connect_completed_state(1),
            {"last_exit": 1, "board_connection_state": "disconnected", "status": "Board host disconnected: connect failed"},
        )

    def test_command_completion_states_match_current_status_text(self) -> None:
        self.assertEqual(jobs.stopped_state("Build", 130), {"last_exit": 130, "status": "Build: stopped (130)"})
        self.assertEqual(jobs.command_failed_state("Build", 2), {"last_exit": 2, "status": "Build: exit 2"})

    def test_completed_process_action_matches_poll_completion_branches(self) -> None:
        self.assertEqual(
            jobs.completed_process_action({"title": "Build", "stopping": True}, 130),
            {"action": "finish", "state": {"last_exit": 130, "status": "Build: stopped (130)"}},
        )
        self.assertEqual(
            jobs.completed_process_action({"title": "Connect", "kind": "connect"}, 0),
            {"action": "connect", "state": {"last_exit": 0, "connection_state": "connected", "status": "Connected"}},
        )
        self.assertEqual(
            jobs.completed_process_action({"title": "Connect board", "kind": "board-connect"}, 1),
            {
                "action": "board-connect",
                "state": {
                    "last_exit": 1,
                    "board_connection_state": "disconnected",
                    "status": "Board host disconnected: connect failed",
                },
            },
        )
        self.assertEqual(
            jobs.completed_process_action({"title": "Build"}, 2),
            {"action": "finish", "state": {"last_exit": 2, "status": "Build: exit 2"}},
        )
        self.assertEqual(jobs.completed_process_action({"title": "Build"}, 0), {"action": "advance", "state": {}})


if __name__ == "__main__":
    unittest.main()
