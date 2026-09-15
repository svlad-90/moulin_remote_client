from __future__ import annotations

import io
import signal
import sys
import unittest

from components.process.api import execution


class ProcessCommandBehaviorTests(unittest.TestCase):
    def test_run_command_echoes_and_returns_completed_process(self) -> None:
        service = execution.process_execution_service()
        echo = io.StringIO()

        result = service.run_command(
            [sys.executable, "-c", "print('ok')"],
            echo_stream=echo,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("+ ", echo.getvalue())

    def test_capture_command_echoes_to_requested_stream_and_returns_stdout(self) -> None:
        service = execution.process_execution_service()
        echo = io.StringIO()

        output = service.capture_command(
            [sys.executable, "-c", "print('captured')"],
            echo_stream=echo,
        )

        self.assertEqual(output, "captured\n")
        self.assertIn("+ ", echo.getvalue())

    def test_terminate_process_group_delegates_signal_and_ignores_missing_group(self) -> None:
        service = execution.process_execution_service()
        with unittest.mock.patch("components.process.src.commands.os.killpg") as killpg:
            service.terminate_process_group(123, signal.SIGTERM)
        killpg.assert_called_once_with(123, signal.SIGTERM)

        with unittest.mock.patch("components.process.src.commands.os.killpg", side_effect=ProcessLookupError):
            service.terminate_process_group(456, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
