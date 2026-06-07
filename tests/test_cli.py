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

        mock_dashboard.assert_called_once()
        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["refresh_interval"], 3.5)
        self.assertEqual(kwargs["docker_timeout"], 12.0)
        self.assertIsNone(kwargs["docker_host"])
        self.assertEqual(kwargs["theme"], "dark")
        # No config file -> no explicit exec_presets override.
        self.assertIsNone(kwargs["exec_presets"])
        # log_tail_limit comes from the Config default when no override exists.
        self.assertEqual(kwargs["log_tail_limit"], 40)
        # New: a Config object must always be passed in.
        self.assertIsNotNone(kwargs["config"])
        self.assertEqual(kwargs["config"].refresh_interval, 3.5)
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

        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["refresh_interval"], 0.5)
        self.assertEqual(kwargs["docker_timeout"], 1.0)

    @patch("docktui.cli.ContainerDashboard")
    @patch("sys.argv", ["docktui", "--host", "ssh://user@host", "--theme", "light"])
    def test_cli_passes_host_and_theme_options(self, mock_dashboard):
        main()

        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["docker_host"], "ssh://user@host")
        self.assertEqual(kwargs["theme"], "light")
        self.assertEqual(kwargs["config"].theme, "light")

    @patch("docktui.cli.ContainerDashboard")
    @patch("docktui.cli.load_config")
    @patch("sys.argv", ["docktui"])
    def test_cli_loads_config_defaults(self, mock_load_config, mock_dashboard):
        mock_load_config.return_value = {
            "refresh_interval": 4.5,
            "docker_timeout": 15.0,
            "theme": "high-contrast",
            "exec_presets": ["echo 1"],
            "log_tail_limit": 100,
        }
        main()

        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["config"].refresh_interval, 4.5)
        self.assertEqual(kwargs["config"].docker_timeout, 15.0)
        self.assertEqual(kwargs["config"].theme, "high_contrast")
        self.assertEqual(kwargs["config"].exec_presets, ["echo 1"])
        self.assertEqual(kwargs["config"].log_tail_limit, 100)


if __name__ == "__main__":
    unittest.main()
