import unittest
from email.message import Message

import prepare_event_evidence as evidence


class FakeResponse:
    def __init__(self, status=200, url="https://example.test/final.zip", headers=None):
        self.status = status
        self._url = url
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class EventEvidenceTests(unittest.TestCase):
    def test_sheet_index_is_small_and_selected_before_imagery(self):
        source = evidence.event_sources()["kamnik_2023_sheet_index"]
        self.assertEqual(source["download_priority"], "required-first")
        self.assertLess(source["estimated_size_bytes"], evidence.LARGE_DOWNLOAD_BYTES)

    def test_large_archive_requires_explicit_opt_in(self):
        source = evidence.event_sources()["kamnik_2023_ortho_rgb"]
        with self.assertRaisesRegex(RuntimeError, "sheet index"):
            evidence.download_source(source, allow_large=False)

    def test_metadata_preserves_final_url_and_length(self):
        response = FakeResponse(headers={"Content-Length": "123", "ETag": "abc"})
        metadata = evidence.response_metadata(response, "HEAD")
        self.assertEqual(metadata["final_url"], "https://example.test/final.zip")
        self.assertEqual(metadata["content_length"], 123)
        self.assertEqual(metadata["etag"], "abc")

    def test_record_exposes_evidence_limitations(self):
        source = evidence.event_sources()["emsr680_products"]
        record = evidence.source_record(source, {"status": 200})
        self.assertIn("never the sole event label", record["limitation"])


if __name__ == "__main__":
    unittest.main()
