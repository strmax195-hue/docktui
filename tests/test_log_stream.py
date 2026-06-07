import unittest
from unittest.mock import MagicMock, patch

from docktui.log_stream import LineStreamer


class TestLineStreamer(unittest.TestCase):
    def test_constructor_does_not_start_process(self):
        streamer = LineStreamer(["echo", "hi"])
        self.assertIsNone(streamer._process)
        self.assertFalse(streamer.is_running())

    def test_stop_is_safe_when_never_started(self):
        streamer = LineStreamer(["echo", "hi"])
        streamer.stop()  # should not raise
        self.assertFalse(streamer.is_running())

    @patch("subprocess.Popen")
    def test_start_returns_error_when_popen_fails(self, mock_popen):
        mock_popen.side_effect = OSError("docker not found")
        streamer = LineStreamer(["docker", "logs", "x"])
        result = streamer.start()
        self.assertIsNotNone(result)
        self.assertIn("Error starting stream", result)

    def test_callback_receives_lines(self):
        # Inject a fake process with controllable output.
        streamer = LineStreamer(["echo", "hi"])
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_stdout = MagicMock()
        fake_stdout.__iter__ = lambda self: iter(["line one\n", "line two\n"])
        fake_proc.stdout = fake_stdout
        fake_proc.stderr = None
        streamer._process = fake_proc
        streamer._stop_event.clear()

        seen: list = []
        streamer.on_line = lambda line: seen.append(line)
        # Drive the reader thread directly (don't spawn real threads).
        streamer._reader(fake_stdout)

        self.assertIn("line one", seen)
        self.assertIn("line two", seen)

    def test_stop_terminates_running_process(self):
        streamer = LineStreamer(["echo", "hi"])
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        streamer._process = fake_proc

        streamer.stop(timeout=0.05)

        fake_proc.terminate.assert_called_once()
        # The fake process's wait() will return quickly; no kill needed.
        self.assertIsNone(streamer._process)


if __name__ == "__main__":
    unittest.main()
