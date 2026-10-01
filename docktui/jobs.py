"""Bounded background jobs; results are applied by the UI thread."""

import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from .processes import close_windows_tree, kill_process_tree, own_windows_tree


class JobRunner:
    def __init__(self, workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="docktui")
        self._active: dict[str, threading.Event] = {}
        self._results: queue.Queue = queue.Queue()
        self._condition = threading.Condition()
        self._working = 0
        self._closed = False

    @property
    def busy(self) -> bool:
        with self._condition:
            return bool(self._active)

    def submit(
        self,
        key: str,
        generation: int,
        work: Callable[[threading.Event], Any],
        apply: Callable[[Any], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> bool:
        with self._condition:
            if self._closed or key in self._active:
                return False
            cancel = threading.Event()
            self._active[key] = cancel
            self._working += 1

        def execute() -> None:
            value, error = None, None
            try:
                if not cancel.is_set():
                    value = work(cancel)
            except Exception as exc:
                error = exc
            finally:
                self._results.put((key, generation, cancel, value, error, apply, on_error))
                with self._condition:
                    self._working -= 1
                    self._condition.notify_all()

        self._executor.submit(execute)
        return True

    def drain(self, generation: int) -> None:
        while True:
            try:
                key, owner, cancel, value, error, apply, on_error = self._results.get_nowait()
            except queue.Empty:
                return
            with self._condition:
                if self._active.get(key) is cancel:
                    self._active.pop(key)
            if owner != generation or cancel.is_set():
                continue
            if error is not None:
                if on_error is not None:
                    on_error(error)
            else:
                apply(value)

    def cancel_prefix(self, prefix: str) -> None:
        with self._condition:
            for key in list(self._active):
                if key.startswith(prefix):
                    self._active.pop(key).set()

    def cancel_all(self) -> None:
        with self._condition:
            for cancel in self._active.values():
                cancel.set()

    def wait_idle(self, timeout: float) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self._working == 0, timeout)

    def shutdown(self) -> None:
        self.cancel_all()
        self._closed = True
        self._executor.shutdown(wait=False)


def run_cancellable(
    cmd: list[str], cancel: threading.Event, **kwargs
) -> subprocess.CompletedProcess:
    """subprocess.run semantics with bounded waits and explicit cancellation."""
    check = kwargs.pop("check", False)
    timeout = kwargs.pop("timeout", None)
    data = kwargs.pop("input", None)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if data is not None:
        kwargs["stdin"] = subprocess.PIPE
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout if timeout is not None else None
    process = subprocess.Popen(cmd, **kwargs)
    owner = own_windows_tree(process)
    cleanup_finished = True
    try:
        while True:
            if cancel.is_set():
                raise RuntimeError("Operation canceled; Docker-side work may already have started.")
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                stdout, stderr = process.communicate(data, timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                data = None
        result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, cmd, stdout, stderr)
        return result
    except BaseException:
        kill_process_tree(process, owner)
        owner = None
        try:
            process.communicate(timeout=0.25)
        except subprocess.TimeoutExpired:
            # Do not close pipes from this thread while a Windows reader owns
            # their lock. A daemon cleanup reader finishes when EOF arrives.
            cleanup_finished = False
            threading.Thread(target=process.communicate, daemon=True).start()
        process.wait(timeout=0.5)
        raise
    finally:
        close_windows_tree(owner)
        if cleanup_finished:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
