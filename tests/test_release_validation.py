import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


class TestReleaseValidation(unittest.TestCase):
    def test_tag_and_built_metadata_must_match_source(self):
        spec = importlib.util.spec_from_file_location('validate_release', 'scripts/validate_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / 'docktui.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('docktui-1.5.0.dist-info/METADATA', 'Name: docktui\nVersion: 1.5.0\n')
            module.verify_version(wheel, '1.5.0', 'v1.5.0')
            with self.assertRaises(ValueError):
                module.verify_version(wheel, '1.5.0', 'v1.4.0')
            with self.assertRaises(ValueError):
                module.verify_version(wheel, '1.6.0', 'v1.6.0')
