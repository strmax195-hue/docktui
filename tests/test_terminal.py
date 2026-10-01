import os
import signal
import subprocess
import sys
import time
import unittest


@unittest.skipUnless(os.name == "posix", "Unix PTY coverage")
class TestTerminal(unittest.TestCase):
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
                    # macOS PTYs have small output buffers; keep draining while
                    # the dashboard redraws and restores the terminal.
                    deadline = time.monotonic() + 5
                    while process.poll() is None and time.monotonic() < deadline:
                        if select.select([master], [], [], 0.05)[0]:
                            output += os.read(master, 65536)
                    self.assertEqual(process.wait(timeout=1), 0, output.decode(errors="replace"))
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
            patch.object(terminal.msvcrt, "getch", side_effect=[b"\xe0", b"H", b"q"]),
        ):
            self.assertEqual(terminal.get_key_nonblocking(), "up")
            self.assertEqual(terminal.get_key_nonblocking(), "q")
        with patch.object(terminal.os, "system"):
            terminal.init_terminal()
            terminal.restore_terminal()
