import tempfile
import unittest
from pathlib import Path

import input_digests


class InputDigestTests(unittest.TestCase):
    def test_restartable_hash_inventory_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.laz"
            second = root / "b.laz"
            first.write_bytes(b"abc")
            second.write_bytes(b"def")
            output = root / "digests.json"
            one = input_digests.build([first, second], output)
            two = input_digests.build([first, second], output)
            self.assertEqual(one, two)
            self.assertEqual(len(two["files"]), 2)


if __name__ == "__main__":
    unittest.main()
