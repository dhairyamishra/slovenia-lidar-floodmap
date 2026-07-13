import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import download_tiles


ROOT = Path(__file__).resolve().parent


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}


class FailingResponse(FakeResponse):
    def __init__(self, payload):
        super().__init__(payload)
        self.read_count = 0

    def read(self, size=-1):
        self.read_count += 1
        if self.read_count > 1:
            raise OSError("simulated interrupted transfer")
        return super().read(2)


class AtomicDownloadTests(unittest.TestCase):
    def test_validity_expansion_batch_has_exact_nonoverlapping_tile_contract(self):
        batch = json.loads((
            ROOT / "validation" / "validity_expansion_2026_07.json"
        ).read_text(encoding="utf-8"))
        selected = set()
        for chunk in batch["chunks"]:
            chunk_tiles = {
                (easting, northing)
                for easting in range(chunk["e_min"], chunk["e_max"] + 1)
                for northing in range(chunk["n_min"], chunk["n_max"] + 1)
            }
            self.assertEqual(len(chunk_tiles), 25)
            self.assertTrue(selected.isdisjoint(chunk_tiles))
            selected.update(chunk_tiles)
        self.assertEqual(len(selected), batch["selected_tile_positions"])
        self.assertEqual(
            sum(chunk["new_tiles"] for chunk in batch["chunks"]),
            batch["expected_new_tiles"],
        )

    def test_success_renames_part_file_only_after_complete_transfer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(download_tiles, "DATA_DIR", root), patch.object(
                download_tiles, "urlopen", return_value=FakeResponse(b"complete-laz")
            ):
                self.assertTrue(download_tiles.download_tile(460, 100, "05-ljubljana", False))
            self.assertEqual((root / "GKOT_460_100.laz").read_bytes(), b"complete-laz")
            self.assertFalse((root / "GKOT_460_100.laz.part").exists())

    def test_failed_transfer_removes_part_file_and_never_creates_final_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(download_tiles, "DATA_DIR", root), patch.object(
                download_tiles, "urlopen", return_value=FailingResponse(b"incomplete")
            ):
                self.assertFalse(download_tiles.download_tile(460, 100, "05-ljubljana", False))
            self.assertFalse((root / "GKOT_460_100.laz").exists())
            self.assertFalse((root / "GKOT_460_100.laz.part").exists())


if __name__ == "__main__":
    unittest.main()
