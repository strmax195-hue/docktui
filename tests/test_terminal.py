import os
import signal
import subprocess
import sys
import time
import unittest


def wait_for_pty_exit(process, master, timeout=5):
    import select

    # Keep consuming output while the child restores the terminal. A full
    # macOS PTY buffer can otherwise block the last write during shutdown.
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        if select.select([master], [], [], 0.05)[0]:
            os.read(master, 65536)
    return process.wait(timeout=1)


def expect_pty_output(process, master, needle):
    import select

    data = b""
    deadline = time.monotonic() + 6
    while needle not in data and time.monotonic() < deadline:
        if select.select([master], [], [], 0.1)[0]:
            data += os.read(master, 65536)
        if process.poll() is not None:
            break
    if needle not in data:
        raise AssertionError(f"{needle!r} missing from {data.decode(errors='replace')}")


@unittest.skipUnless(os.name == "posix", "Unix PTY coverage")
class TestTerminal(unittest.TestCase):
    def test_offline_demo_from_queue_to_evidence_in_a_terminal(self):
        import pty
        import tempfile
        import termios

        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        before = termios.tcgetattr(slave)
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(
                os.environ,
                PATH=tmp,
                COLUMNS="80",
                LINES="24",
                PYTHONIOENCODING="utf-8",
                DOCKTUI_CONFIG=os.path.join(tmp, "bad.json"),
            )
            with open(env["DOCKTUI_CONFIG"], "w") as config:
                config.write("invalid configuration")
            process = subprocess.Popen(
                [sys.executable, "-m", "docktui", "demo"],
                env=env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
            )
            try:
                expect_pty_output(process, master, b"checkout-worker-1")
                os.write(master, b"\r")
                expect_pty_output(process, master, b"Schema version 18 required")
                os.write(master, b"\x1b")
                expect_pty_output(process, master, b"Needs attention")
                os.write(master, b"a")
                expect_pty_output(process, master, b"checkout-seed-1")
                os.write(master, b"?")
                expect_pty_output(process, master, b"Keyboard help")
                process.send_signal(signal.SIGINT)
                self.assertEqual(wait_for_pty_exit(process, master), 0)
                after = termios.tcgetattr(slave)
                pending = getattr(termios, "PENDIN", 0)
                before[3] &= ~pending
                after[3] &= ~pending
                self.assertEqual(after, before)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_help_paging_and_registry_search_through_cli(self):
        import pty
        import tempfile

        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(
                os.environ,
                PATH=tmp,
                DOCKTUI_CONFIG=os.path.join(tmp, "config.json"),
                PYTHONIOENCODING="utf-8",
                COLUMNS="80",
                LINES="24",
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "docktui"], env=env, stdin=slave, stdout=slave, stderr=slave
            )
            try:

                def expect(needle):
                    expect_pty_output(process, master, needle)

                expect(b"Docker CLI not found")
                os.write(master, b"?")
                expect(b"Containers and Compose")
                os.write(master, b"\x1b[F")  # End, through the terminal decoder.
                expect(b"Settings and cleanup")
                os.write(master, b"?")
                expect(b"Docker CLI not found")
                os.write(master, b"3f")
                expect(b"Search Docker Hub:")
                os.write(master, b"queue\r")
                expect(b"Search failed: Docker CLI not found")
                os.write(master, b"\x1b")
                expect(b"Install the Docker CLI")
                os.write(master, b"q")
                self.assertEqual(wait_for_pty_exit(process, master), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_resize_state_lives_in_terminal_module(self):
        from docktui import terminal

        terminal.RESIZE_REQUESTED = False
        terminal.handle_resize()
        self.assertTrue(terminal.RESIZE_REQUESTED)

    def test_tui_restores_pty_after_quit_and_interrupt(self):
        import pty
        import select
        import termios

        code = (
            "from docktui.tui import ContainerDashboard\n"
            "d=ContainerDashboard();d.client.docker_bin=None\n"
            "d.enable_mouse_tracking=lambda: print('PTY_READY', flush=True)\n"
            "try: d.run()\n"
            "except KeyboardInterrupt: pass\n"
        )
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                master, slave = pty.openpty()
                before = termios.tcgetattr(slave)
                process = subprocess.Popen(
                    [sys.executable, "-c", code], stdin=slave, stdout=slave, stderr=slave
                )
                try:
                    output = b""
                    deadline = time.monotonic() + 10
                    while b"PTY_READY" not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            output += os.read(master, 65536)
                    self.assertIn(b"PTY_READY", output)
                    process.send_signal(signal.SIGWINCH)
                    if interrupt:
                        process.send_signal(signal.SIGINT)
                    else:
                        os.write(master, b"q")
                    self.assertEqual(
                        wait_for_pty_exit(process, master), 0, output.decode(errors="replace")
                    )
                    after = termios.tcgetattr(slave)
                    # Darwin sets kernel-managed PENDIN when restoring canonical
                    # input. It does not change the user-visible terminal modes.
                    pending = getattr(termios, "PENDIN", 0)
                    before[3] &= ~pending
                    after[3] &= ~pending
                    self.assertEqual(after, before)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    os.close(master)
                    os.close(slave)

    def test_interrupt_handler_requests_quit_without_raising_and_restores_signal(self):
        from docktui import terminal

        before = signal.getsignal(signal.SIGINT)
        called = []
        with terminal.interrupt_handler(lambda: called.append(True)):
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        self.assertEqual(called, [True])
        self.assertEqual(signal.getsignal(signal.SIGINT), before)


@unittest.skipUnless(os.name == "nt", "native Windows keyboard lifecycle")
class TestWindowsTerminal(unittest.TestCase):
    def test_keyboard_and_cleanup(self):
        from unittest.mock import patch

        from docktui import terminal

        with (
            patch.object(terminal.msvcrt, "kbhit", return_value=True),
            patch.object(
                terminal.msvcrt, "getwch", side_effect=["\xe0", "H", "q", "я", "\xe0", "Q"]
            ),
        ):
            self.assertEqual(terminal.get_key_nonblocking(), "up")
            self.assertEqual(terminal.get_key_nonblocking(), "q")
            self.assertEqual(terminal.get_key_nonblocking(), "я")
            self.assertEqual(terminal.get_key_nonblocking(), "page_down")
        with patch.object(terminal.os, "system"):
            terminal.init_terminal()
            terminal.restore_terminal()
