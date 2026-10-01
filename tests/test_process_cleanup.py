import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from docktui.jobs import run_cancellable


class TestProcessCleanup(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'exercise bounded fallback cleanup')
    def test_cleanup_does_not_wait_for_inherited_pipe_forever(self):
        script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(1)']); time.sleep(10)"
        started = time.monotonic()
        with patch('docktui.jobs.os.name', 'other'):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_cancellable([sys.executable,'-c',script], threading.Event(), timeout=.1, capture_output=True, start_new_session=True)
        self.assertLess(time.monotonic()-started, .7)

    @unittest.skipUnless(os.name == 'nt', 'native Windows descendant cleanup')
    def test_windows_deadline_terminates_inherited_pipe_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'survived'
            child = f"import time,pathlib;time.sleep(.8);pathlib.Path({str(marker)!r}).touch();time.sleep(10)"
            script = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(10)"
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                run_cancellable([sys.executable,'-c',script], threading.Event(), timeout=.2, capture_output=True)
            self.assertLess(time.monotonic()-started, 2)
            time.sleep(1)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows stream descendant cleanup')
    def test_windows_stream_stop_terminates_inherited_pipe_child(self):
        from docktui.log_stream import LineStreamer
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'stream-child-survived'
            child = f"import time,pathlib;time.sleep(.8);pathlib.Path({str(marker)!r}).touch();time.sleep(10)"
            script = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);print('ready',flush=True);time.sleep(10)"
            ready = threading.Event()
            streamer = LineStreamer([sys.executable, '-c', script], lambda line: ready.set())
            self.assertIsNone(streamer.start())
            try:
                self.assertTrue(ready.wait(2))
                started = time.monotonic()
                streamer.stop(.1)
                self.assertLess(time.monotonic()-started, 2)
                time.sleep(1)
                self.assertFalse(marker.exists())
            finally:
                streamer.stop()
