from __future__ import annotations

import signal
import unittest
from unittest.mock import patch

from components.process.api import execution


class ProcessExecutionServiceTests(unittest.TestCase):
    def test_service_delegates_run_capture_and_terminate_use_cases(self) -> None:
        service = execution.process_execution_service()

        with (
            patch("components.process.src.execution.process_commands.run_command", return_value="ran") as run_command,
            patch("components.process.src.execution.process_commands.capture_command", return_value="out") as capture_command,
            patch("components.process.src.execution.process_commands.terminate_process_group") as terminate,
        ):
            self.assertEqual(service.run_command(["true"], check=False), "ran")
            self.assertEqual(service.capture_command(["pwd"], echo=False, timeout=1.0), "out")
            service.terminate_process_group(123, signal.SIGTERM)

        run_command.assert_called_once_with(["true"], check=False, env=None, echo=True, echo_stream=None)
        capture_command.assert_called_once_with(["pwd"], echo=False, timeout=1.0, echo_stream=None)
        terminate.assert_called_once_with(123, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
