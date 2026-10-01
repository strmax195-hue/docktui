import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docktui.config import Config
from docktui.doctor import FAIL, check_config


class TestConfigSafety(unittest.TestCase):
    def test_replace_failure_keeps_old_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"theme":"light"}', encoding="utf-8")
            original = path.read_bytes()
            with patch("docktui.config.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    Config().save(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_nonfinite_and_nested_values_are_safe_and_diagnosed(self):
        raw = {
            "refresh_interval": float("nan"),
            "log_max": float("inf"),
            "log_min": -2,
            "endpoints": [{"name": [], "host": 42}],
            "log_highlights": [{"pattern": "["}],
            "active_endpoint": "missing",
            "hotkey_overlays": {"x": []},
        }
        config = Config.from_dict(raw)
        config.validate()
        self.assertTrue(math.isfinite(config.refresh_interval))
        self.assertGreaterEqual(config.log_min, 1)
        self.assertLessEqual(config.log_min, config.log_tail_limit)
        self.assertLessEqual(config.log_tail_limit, config.log_max)
        self.assertEqual(config.endpoints, [])
        self.assertEqual(config.log_highlights, [])
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                config.resolve_host()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            result = check_config(path)
            self.assertEqual(result.status, FAIL)
            for field in (
                "refresh_interval",
                "log_max",
                "endpoints",
                "log_highlights",
                "active_endpoint",
            ):
                self.assertIn(field, result.detail)

    def test_inconsistent_limits_and_duplicate_endpoints_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "log_min": 100,
                        "log_max": 50,
                        "endpoints": [
                            {"name": "a", "host": "ssh://a"},
                            {"name": "a", "host": "ssh://b"},
                        ],
                    }
                )
            )
            error = Config.validate_file(path)
            self.assertIn("log_min", error)
            self.assertIn("duplicate", error)
