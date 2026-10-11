"""Hash audit must detect changed source text before it can be cited."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_source_hashes", PROJECT / "scripts/check_source_hashes.py")
hashes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hashes)


class HashAuditTests(unittest.TestCase):
    def test_original_and_normalized_tamper_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "sources/raw/synthetic.html"
            normalized = root / "sources/normalized/synthetic.json"
            raw.parent.mkdir(parents=True)
            normalized.parent.mkdir(parents=True)
            raw.write_bytes(b"SYNTHETIC RAW")
            normalized.write_text('[{"number": 1, "text": "SYNTHETIC"}]')
            manifest = {"synthetic": {"raw_path": "sources/raw/synthetic.html",
                                      "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                                      "normalized_sha256": hashlib.sha256(normalized.read_bytes()).hexdigest()}}
            (root / "sources/SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
            self.assertTrue(hashes.audit(root)["hash_audit_pass"])
            raw.write_bytes(b"CHANGED RAW")
            self.assertFalse(hashes.audit(root)["hash_audit_pass"])
            raw.write_bytes(b"SYNTHETIC RAW")
            normalized.write_text('[{"number": 1, "text": "CHANGED"}]')
            self.assertFalse(hashes.audit(root)["hash_audit_pass"])


if __name__ == "__main__":
    unittest.main()
