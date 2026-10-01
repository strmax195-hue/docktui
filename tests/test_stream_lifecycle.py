import io
import sys
import threading
import unittest

from docktui.log_stream import LineStreamer


class TestStreamLifecycle(unittest.TestCase):
    def test_history_is_bounded_to_last_500_lines(self):
        streamer = LineStreamer(["unused"])
        streamer._reader(io.StringIO("".join(f"line {i}\n" for i in range(100000))))
        self.assertEqual(len(streamer.lines), 500)
        self.assertEqual(streamer.lines[0], "line 99500")
        self.assertEqual(streamer.lines[-1], "line 99999")

    def test_natural_exit_notifies_once(self):
        finished = threading.Event()
        calls = []

        def on_stop():
            calls.append(True)
            finished.set()

        streamer = LineStreamer([sys.executable, "-c", "print('hello')"], on_stop=on_stop)
        self.assertIsNone(streamer.start())
        try:
            self.assertTrue(finished.wait(2), "natural EOF must notify completion")
            self.assertEqual(streamer.lines, ["hello"])
            streamer.stop()
            streamer.stop()
            self.assertEqual(len(calls), 1)
        finally:
            streamer.stop()

    def test_cancel_and_failure_are_distinct(self):
        finished = threading.Event()
        results = []

        def complete(result):
            results.append(result)
            finished.set()

        streamer = LineStreamer([sys.executable, "-c", "raise SystemExit(7)"], on_complete=complete)
        self.assertIsNone(streamer.start())
        self.assertTrue(finished.wait(2))
        self.assertEqual(results[0].returncode, 7)
        self.assertFalse(results[0].cancelled)
        streamer.stop()
        self.assertEqual(len(results), 1)

        finished.clear()
        results.clear()
        streamer = LineStreamer(
            [sys.executable, "-c", "import time; time.sleep(30)"], on_complete=complete
        )
        streamer.start()
        streamer.stop()
        self.assertTrue(finished.wait(2))
        self.assertTrue(results[0].cancelled)
        self.assertFalse(streamer.is_running())
