import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from docktui import __version__
from docktui.cli import main


class TestCli(unittest.TestCase):
    @patch("docktui.cli.ContainerDashboard")
    @patch("sys.argv", ["docktui", "--refresh-interval", "3.5", "--docker-timeout", "12"])
    def test_cli_passes_runtime_options_to_dashboard(self, mock_dashboard):
        main()

        mock_dashboard.assert_called_once_with(refresh_interval=3.5, docker_timeout=12.0)
        mock_dashboard.return_value.run.assert_called_once()

    @patch("sys.argv", ["docktui", "--version"])
    def test_cli_version(self):
        stdout = io.StringIO()

        with self.assertRaises(SystemExit) as cm, redirect_stdout(stdout):
            main()

        self.assertEqual(cm.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())

    @patch("docktui.cli.ContainerDashboard")
    @patch("sys.argv", ["docktui", "--refresh-interval", "0.1", "--docker-timeout", "0.1"])
    def test_cli_clamps_low_runtime_options(self, mock_dashboard):
        main()

        mock_dashboard.assert_called_once_with(refresh_interval=0.5, docker_timeout=1.0)


if __name__ == "__main__":
    unittest.main()
