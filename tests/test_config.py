import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docktui.config import Config


class TestConfig(unittest.TestCase):
    def test_default_config_has_sane_values(self):
        config = Config()
        self.assertEqual(config.refresh_interval, 2.0)
        self.assertEqual(config.docker_timeout, 10.0)
        self.assertEqual(config.theme, "dark")
        self.assertEqual(config.log_tail_limit, 40)
        self.assertEqual(config.exec_history_cap, 10)
        self.assertGreater(len(config.exec_presets), 0)
        self.assertEqual(config.endpoints, [])
        self.assertEqual(config.log_highlights, [])
        self.assertIsNone(config.active_endpoint)

    def test_from_dict_ignores_unknown_keys(self):
        config = Config.from_dict({"refresh_interval": 5.0, "unknown": "ignored"})
        self.assertEqual(config.refresh_interval, 5.0)

    def test_from_dict_coerces_list_fields(self):
        # Strings are wrapped into a one-element list; non-list, non-string values
        # are dropped to avoid crashes on malformed config files.
        config = Config.from_dict({"exec_presets": "ls -la", "endpoints": 42})
        self.assertEqual(config.exec_presets, ["ls -la"])
        self.assertEqual(config.endpoints, [])

    def test_from_dict_normalizes_unknown_theme(self):
        config = Config.from_dict({"theme": "neon"})
        self.assertEqual(config.theme, "dark")

    def test_validate_clamps_out_of_range_values(self):
        config = Config(
            refresh_interval=0.0,
            docker_timeout=0.0,
            log_tail_limit=9999,
            cpu_alert_threshold=150.0,
            theme="bogus",
        )
        config.validate()
        self.assertEqual(config.refresh_interval, 2.0)
        self.assertEqual(config.docker_timeout, 10.0)
        self.assertLessEqual(config.log_tail_limit, 500)
        self.assertEqual(config.cpu_alert_threshold, 80.0)
        self.assertEqual(config.theme, "dark")

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "config.json"
            original = Config(
                refresh_interval=3.0,
                theme="light",
                log_tail_limit=100,
                exec_presets=["sh", "ls"],
                endpoints=[{"name": "remote", "host": "ssh://user@host"}],
            )
            original.save(target)
            self.assertTrue(target.is_file())

            loaded = Config.load(target)
            self.assertEqual(loaded.refresh_interval, 3.0)
            self.assertEqual(loaded.theme, "light")
            self.assertEqual(loaded.log_tail_limit, 100)
            self.assertEqual(loaded.exec_presets, ["sh", "ls"])
            self.assertEqual(loaded.endpoints[0]["name"], "remote")

    def test_load_falls_back_to_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config.load(Path(tmp) / "missing.json")
            self.assertEqual(config.theme, "dark")
            self.assertEqual(config.refresh_interval, 2.0)

    def test_load_handles_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "broken.json"
            target.write_text("{not valid json", encoding="utf-8")
            config = Config.load(target)
            self.assertEqual(config.theme, "dark")

    def test_load_uses_known_candidate_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "myconfig.json"
            target.write_text(json.dumps({"theme": "light"}), encoding="utf-8")
            with patch.object(Config, "_CANDIDATE_PATHS", (target,)):
                loaded = Config.load()
            self.assertEqual(loaded.theme, "light")

    def test_to_dict_excludes_private_fields(self):
        config = Config()
        data = config.to_dict()
        self.assertNotIn("_CANDIDATE_PATHS", data)
        self.assertIn("refresh_interval", data)
        self.assertIn("endpoints", data)


if __name__ == "__main__":
    unittest.main()
