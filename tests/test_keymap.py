import unittest

from docktui.keymap import Keymap


def _noop(key: str = None) -> None:
    return None


class TestKeymap(unittest.TestCase):
    def test_dispatch_routes_to_matching_handler(self):
        keymap = Keymap()
        calls: list = []
        keymap.register("main", "q", lambda k: calls.append(("main", k)))
        keymap.register("logs", "q", lambda k: calls.append(("logs", k)))

        keymap.dispatch("main", "q")
        keymap.dispatch("logs", "q")

        self.assertEqual(calls, [("main", "q"), ("logs", "q")])

    def test_dispatch_falls_back_to_global(self):
        keymap = Keymap()
        calls: list = []
        keymap.register_global("?", lambda k: calls.append(("global", k)))

        handled = keymap.dispatch("main", "?")
        self.assertTrue(handled)
        self.assertEqual(calls, [("global", "?")])

    def test_dispatch_returns_false_when_unhandled(self):
        keymap = Keymap()
        keymap.register("main", "q", _noop)
        self.assertFalse(keymap.dispatch("main", "x"))

    def test_alias_matching(self):
        keymap = Keymap()
        seen: list = []
        keymap.register("main", "up|scroll_up", lambda k: seen.append(k))

        keymap.dispatch("main", "up")
        keymap.dispatch("main", "scroll_up")

        self.assertEqual(seen, ["up", "scroll_up"])

    def test_descriptions_for_view_prefers_view_specific(self):
        keymap = Keymap()
        keymap.register_global("q", _noop, description="Quit everywhere")
        keymap.register("logs", "q", _noop, description="Quit logs view")

        descs = dict(keymap.descriptions_for_view("logs"))
        self.assertEqual(descs["q"], "Quit logs view")

    def test_descriptions_omits_bindings_without_description(self):
        keymap = Keymap()
        keymap.register("main", "q", _noop)  # no description
        keymap.register("main", "x", _noop, description="Do X")

        descs = dict(keymap.descriptions_for_view("main"))
        self.assertNotIn("q", descs)
        self.assertEqual(descs["x"], "Do X")


class TestHotkeyOverlays(unittest.TestCase):
    def test_parse_hotkey(self):
        from docktui.keymap import parse_hotkey

        self.assertEqual(parse_hotkey("ctrl+l"), "\x0c")
        self.assertEqual(parse_hotkey("Ctrl-E"), "\x05")
        self.assertEqual(parse_hotkey("^b"), "\x02")
        # Reserved or unsupported specs are ignored.
        self.assertEqual(parse_hotkey("ctrl+s"), "")
        self.assertEqual(parse_hotkey("ctrl+c"), "")
        self.assertEqual(parse_hotkey("f5"), "")

    def test_resolve_hotkey_overlay(self):
        from docktui.keymap import resolve_hotkey_overlay

        overlays = {"ctrl+l": "ls -l", "ctrl+s": "ignored"}
        self.assertEqual(resolve_hotkey_overlay(overlays, "\x0c"), "ls -l")
        self.assertIsNone(resolve_hotkey_overlay(overlays, "\x13"))
        self.assertIsNone(resolve_hotkey_overlay(overlays, "l"))


if __name__ == "__main__":
    unittest.main()
