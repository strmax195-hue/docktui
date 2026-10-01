import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from docktui.cli import main
from docktui.tui import ContainerDashboard


class TestSaveErrors(unittest.TestCase):
    def test_config_init_reports_save_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = io.StringIO()
            with patch('docktui.config.Config.save', side_effect=OSError('disk failure')):
                with redirect_stdout(io.StringIO()), redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    main(['config','init','--config',str(Path(tmp)/'config.json')])
            self.assertEqual(caught.exception.code, 1)
            self.assertIn('disk failure', error.getvalue())

    def test_endpoint_save_failure_is_visible(self):
        d = ContainerDashboard()
        d.new_endpoint_prompt()
        d.input_dialog.buffer = 'prod|ssh://prod'
        with patch.object(d.config, 'save', side_effect=OSError('disk failure')):
            d.submit_input()
        self.assertIn('save failed', d.status_message.lower())

    def test_exec_does_not_depend_on_unrelated_config_write(self):
        d = ContainerDashboard()
        d.start_exec_input({'id':'a','name':'a'})
        d.input_dialog.buffer = 'echo hi'
        with patch.object(d.config,'save',side_effect=OSError('disk failure')), patch.object(d.client,'exec_command',return_value='hi'):
            d.submit_input()
        self.assertEqual(d.exec_output_lines, ['hi'])
