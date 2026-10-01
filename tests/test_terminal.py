import os
import signal
import subprocess
import sys
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
            "try: d.run()\n"
            "except KeyboardInterrupt: pass\n"
        )
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                master, slave = pty.openpty()
                before = termios.tcgetattr(slave)
                process = subprocess.Popen([sys.executable, "-c", code], stdin=slave, stdout=slave, stderr=slave)
                try:
                    self.assertTrue(select.select([master], [], [], 3)[0])
                    os.read(master, 65536)
                    process.send_signal(signal.SIGWINCH)
                    if interrupt:
                        process.send_signal(signal.SIGINT)
                    else:
                        os.write(master, b"q")
                    self.assertEqual(process.wait(timeout=3), 0)
                    self.assertEqual(termios.tcgetattr(slave), before)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    os.close(master)
                    os.close(slave)
