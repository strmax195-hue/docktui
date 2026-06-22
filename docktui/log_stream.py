"""Background line-streaming utility used by logs, pull progress, etc.

Centralizes the threading + buffering boilerplate that the dashboard needs
for any long-running `docker` invocation that produces output incrementally.
"""

import subprocess
import threading
from typing import Callable, List, Optional


class LineStreamer:
    """Run a subprocess and stream its stdout lines to a thread-safe buffer.

    A `LineStreamer` can be reused by views that want background updates
    (log follow, image pull progress) and stopped cleanly when the user
    navigates away.
    """

    def __init__(
        self,
        cmd: List[str],
        on_line: Optional[Callable[[str], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        text: bool = True,
    ) -> None:
        self.cmd = cmd
        self.on_line = on_line
        self.on_stop = on_stop
        self.text = text
        self._process: Optional[subprocess.Popen] = None
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._lines: List[str] = []

    @property
    def lines(self) -> List[str]:
        with self._lock:
            return list(self._lines)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> Optional[str]:
        """Spawn the subprocess and reader threads. Returns an error string on failure."""
        if self.is_running():
            return None
        try:
            self._process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=self.text,
                encoding="utf-8" if self.text else None,
                errors="replace" if self.text else None,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            return f"Error starting stream: {exc}"

        self._stop_event.clear()
        for stream in (self._process.stdout, self._process.stderr):
            if stream is None:
                continue
            thread = threading.Thread(target=self._reader, args=(stream,), daemon=True)
            thread.start()
            self._threads.append(thread)
        return None

    def _reader(self, stream) -> None:
        try:
            for raw in stream:
                if self._stop_event.is_set():
                    break
                if raw is None:
                    break
                line = raw.rstrip("\n")
                with self._lock:
                    self._lines.append(line)
                if self.on_line is not None:
                    try:
                        self.on_line(line)
                    except Exception:
                        pass
        except Exception:
            pass

    def stop(self, timeout: float = 0.2) -> None:
        """Terminate the subprocess and join reader threads."""
        self._stop_event.set()
        process = self._process
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=timeout)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads = []
        self._process = None
        if self.on_stop is not None:
            try:
                self.on_stop()
            except Exception:
                pass
