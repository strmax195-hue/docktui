import unittest

from docktui.dialogs import DialogResult, PickerOption, apply_dialog_key


def _capture(value: list) -> "callable":
    def cb(_value: str) -> None:
        value.append(_value)

    return cb


class TestDialogs(unittest.TestCase):
    def test_apply_dialog_key_handles_enter(self):
        result = DialogResult(prompt="Enter name", buffer="web", submit=_capture([]))
        handled = apply_dialog_key(result, "enter")
        self.assertTrue(handled)
        self.assertEqual(result.buffer, "web")  # unchanged

    def test_apply_dialog_key_backspace(self):
        result = DialogResult(prompt="Enter name", buffer="web")
        apply_dialog_key(result, "backspace")
        self.assertEqual(result.buffer, "we")

    def test_apply_dialog_key_prints_char(self):
        result = DialogResult(prompt="Enter", buffer="ab")
        apply_dialog_key(result, "c")
        self.assertEqual(result.buffer, "abc")

    def test_apply_dialog_key_ignores_non_printable(self):
        result = DialogResult(prompt="Enter", buffer="ab")
        apply_dialog_key(result, "\x01")
        self.assertEqual(result.buffer, "ab")

    def test_apply_dialog_key_esc_invokes_cancel(self):
        result = DialogResult(prompt="p", buffer="b")
        called: list = []
        result.cancel = lambda: called.append("cancel")
        apply_dialog_key(result, "\x1b")
        self.assertEqual(called, ["cancel"])

    def test_apply_dialog_key_ignores_unknown(self):
        result = DialogResult(prompt="p", buffer="b")
        handled = apply_dialog_key(result, "F1")
        self.assertFalse(handled)


class TestPickerOption(unittest.TestCase):
    def test_default_description_is_empty(self):
        opt = PickerOption(label="Run", value="run")
        self.assertEqual(opt.description, "")
        self.assertEqual(opt.value, "run")


if __name__ == "__main__":
    unittest.main()
