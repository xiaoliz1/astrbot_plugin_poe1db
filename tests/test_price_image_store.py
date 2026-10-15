import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_poe1db.price_image_store import PriceImageStore


class PriceImageStoreTests(unittest.TestCase):
    def test_replacement_survives_restart_and_only_then_removes_old_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PriceImageStore(temporary)
            first = Path(temporary) / "first.png"
            first.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
            old_path = Path(store.save_replacement("international", first, "2026-10-15 10:00:00"))
            self.assertTrue(old_path.is_file())

            second = Path(temporary) / "second.png"
            second.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
            new_path = Path(store.save_replacement("international", second, "2026-10-15 11:00:00"))
            self.assertTrue(new_path.is_file())
            self.assertFalse(old_path.exists())

            restored = PriceImageStore(temporary)
            self.assertEqual(restored.images["international"], str(new_path.resolve()))
            self.assertEqual(restored.updated_at["international"], "2026-10-15 11:00:00")

    def test_failed_replacement_keeps_previous_image_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PriceImageStore(temporary)
            valid = Path(temporary) / "valid.png"
            valid.write_bytes(b"\x89PNG\r\n\x1a\nvalid")
            current = Path(store.save_replacement("national", valid, "today"))
            manifest_before = store.manifest_path.read_text(encoding="utf-8")
            with self.assertRaises(ValueError):
                store.save_replacement("national", Path(temporary) / "missing.png", "tomorrow")
            self.assertTrue(current.is_file())
            self.assertEqual(store.manifest_path.read_text(encoding="utf-8"), manifest_before)
            self.assertEqual(json.loads(manifest_before)["images"]["national"]["filename"], current.name)


if __name__ == "__main__":
    unittest.main()
