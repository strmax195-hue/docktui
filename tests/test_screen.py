import unittest

from docktui.screen import (
    draw_frame,
    draw_status_bar,
    get_terminal_size,
    pad_to_viewport,
    scroll_step,
    slice_viewport,
    truncate,
    viewport_height_for,
)
from docktui.styles import apply_theme_colors, strip_ansi, visible_length


class TestScreen(unittest.TestCase):
    def test_get_terminal_size_returns_positive_dimensions(self):
        size = get_terminal_size()
        self.assertGreater(size.width, 0)
        self.assertGreater(size.height, 0)

    def test_truncate_short_text_is_padded(self):
        self.assertEqual(truncate("hi", 5), "hi   ")

    def test_truncate_long_text_is_ellipsized(self):
        result = truncate("abcdefghij", 5)
        self.assertEqual(result, "ab...")

    def test_truncate_zero_length_returns_empty(self):
        self.assertEqual(truncate("hello", 0), "")

    def test_scroll_step_mouse_wheel_uses_wheel_delta(self):
        self.assertEqual(scroll_step("scroll_up", wheel_delta=3, arrow_delta=1), 3)
        self.assertEqual(scroll_step("scroll_down", wheel_delta=3, arrow_delta=1), 3)

    def test_scroll_step_arrow_keys_use_arrow_delta(self):
        self.assertEqual(scroll_step("up", wheel_delta=3, arrow_delta=1), 1)
        self.assertEqual(scroll_step("down", wheel_delta=3, arrow_delta=1), 1)

    def test_viewport_height_for_subtracts_overhead(self):
        self.assertEqual(viewport_height_for(30, overhead=6), 24)
        self.assertGreaterEqual(viewport_height_for(0, overhead=6), 1)

    def test_slice_viewport_returns_visible_window(self):
        lines = ["a", "b", "c", "d", "e"]
        visible, start, end = slice_viewport(lines, 1, 2)
        self.assertEqual(visible, ["b", "c"])
        self.assertEqual(start, 1)
        self.assertEqual(end, 3)

    def test_slice_viewport_clamps_scroll_index(self):
        lines = ["a", "b"]
        visible, start, end = slice_viewport(lines, 100, 5)
        self.assertEqual(start, 1)
        self.assertEqual(end, 2)

    def test_pad_to_viewport_prints_empty_lines(self):
        # Smoke test: should not raise.
        pad_to_viewport(2, 5)

    def test_draw_frame_does_not_raise_with_safe_string(self):
        # Pure ASCII title to avoid Windows console encoding issues.
        from unittest.mock import patch
        apply_theme_colors("dark")
        with patch("builtins.print"):
            draw_frame("Title", 80)
            draw_status_bar("All good", 80)


class TestStyles(unittest.TestCase):
    def test_apply_theme_colors_returns_normalized_name(self):
        name = apply_theme_colors("high-contrast")
        self.assertEqual(name, "high_contrast")
        name = apply_theme_colors("light")
        self.assertEqual(name, "light")
        name = apply_theme_colors("dark")
        self.assertEqual(name, "dark")
        name = apply_theme_colors("nonexistent")
        self.assertEqual(name, "dark")

    def test_visible_length_ignores_ansi(self):
        apply_theme_colors("dark")
        plain = "hello"
        styled = "\033[32mhello\033[0m"
        self.assertEqual(visible_length(plain), visible_length(styled))

    def test_strip_ansi_removes_escape_codes(self):
        result = strip_ansi("\033[31mred\033[0m text")
        self.assertEqual(result, "red text")


if __name__ == "__main__":
    unittest.main()
