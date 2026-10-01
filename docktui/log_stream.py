"""Bounded subprocess streams with explicit, exactly-once completion."""

import os
import signal
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .processes import close_windows_tree, kill_process_tree, own_windows_tree


@dataclass(frozen=True)
class StreamResult:
    returncode: int
    cancelled: bool = False
    error: str = ""


class LineStreamer:
    def __init__(
        self,
        cmd: list[str],
        on_line: Optional[Callable[[str], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        text: bool = True,
        env: Optional[dict[str, str]] = None,
        max_lines: int = 500,
        on_complete: Optional[Callable[[StreamResult], None]] = None,
    ) -> None:
        self.cmd = cmd
        self.on_line = on_line
        self.on_stop = on_stop
        self.on_complete = on_complete
        self.text = text
        self.env = dict(env) if env is not None else None
        self._process: Optional[subprocess.Popen] = None
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=max(1, max_lines))
        self._completed = False
        self._cancelled = False
        self._owns_group = False
        self._windows_owner: Any = None
        self.result: Optional[StreamResult] = None

    @property
    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> Optional[str]:
        if self.is_running():
            return None
        if self._process is not None:
            self.stop()
        self._stop_event.clear()
        self._completed = False
        self._cancelled = False
        self.result = None
        self._lines.clear()
        options: dict = {}
        if os.name == "posix":
            options["start_new_session"] = True
        elif os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        try:
            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=self.text,
                encoding="utf-8" if self.text else None,
                errors="replace" if self.text else None,
                bufsize=1,
                env=self.env,
                **options,
            )
        except (OSError, ValueError) as exc:
            error = f"Error starting stream: {exc}"
            self._finish(StreamResult(-1, error=error))
            return error
        self._process = process
        self._windows_owner = own_windows_tree(process)
        self._owns_group = True
        readers = []
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                thread = threading.Thread(target=self._reader, args=(stream,), daemon=True)
                readers.append(thread)
                thread.start()
        waiter = threading.Thread(target=self._wait, args=(process, readers), daemon=True)
        self._threads = readers + [waiter]
        waiter.start()
        return None

    def _reader(self, stream) -> None:
        try:
            for raw in stream:
                if self._stop_event.is_set():
                    break
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                line = raw.rstrip("\r\n")[:16384]
                with self._lock:
                    self._lines.append(line)
                if self.on_line is not None:
                    self.on_line(line)
        except (OSError, ValueError):
            pass  # Pipes may close during cancellation.
        finally:
            stream.close()

    def _wait(self, process: subprocess.Popen, readers: list[threading.Thread]) -> None:
        code = process.wait()
        for thread in readers:
            thread.join(timeout=1.0)
        if any(thread.is_alive() for thread in readers):
            self._signal_process(process, kill=True)
            for thread in readers:
                thread.join(timeout=1.0)
        if self._owns_group and os.name == "posix":
            self._signal_process(process, kill=True)
        close_windows_tree(self._take_windows_owner())
        self._owns_group = False
        self._finish(StreamResult(code, self._cancelled))

    def _finish(self, result: StreamResult) -> None:
        with self._lock:
            if self._completed:
                return
            self._completed = True
            self.result = result
        if self.on_complete is not None:
            self.on_complete(result)
        if self.on_stop is not None:
            self.on_stop()

    def _take_windows_owner(self) -> Any:
        with self._lock:
            owner = self._windows_owner
            self._windows_owner = None
            return owner

    def _signal_process(self, process: subprocess.Popen, kill: bool = False) -> None:
        if kill and self._owns_group:
            kill_process_tree(process, self._take_windows_owner())
            return
        if self._owns_group and os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)
                return
            except ProcessLookupError:
                return
        if kill:
            process.kill()
        else:
            process.terminate()

    def stop(self, timeout: float = 0.2) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            self._cancelled = True
            self._stop_event.set()
            try:
                self._signal_process(process)
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._signal_process(process, kill=True)
                process.wait(timeout=max(timeout, 1.0))
            except ProcessLookupError:
                pass
        if self._owns_group:
            self._signal_process(process, kill=True)
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(timeout, 1.0))
        code = process.poll()
        self._finish(StreamResult(code if isinstance(code, int) else -1, self._cancelled))
        if not any(thread.is_alive() for thread in self._threads):
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        self._threads = []
        self._process = None
