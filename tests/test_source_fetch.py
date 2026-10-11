"""Fetch failures must be visible to new installers and fail the command."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_pipeline", PROJECT / "scripts/source_pipeline.py")
source_pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_pipeline)


class FetchTests(unittest.TestCase):
    def test_failed_download_exits_nonzero_and_records_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = {"synthetic": ("SYNTHETIC", "https://example.invalid/legal", "SYNTHETIC")}
            failed = SimpleNamespace(returncode=28, stderr="test timeout")
            with (mock.patch.object(source_pipeline, "ROOT", root),
                  mock.patch.object(source_pipeline, "CATALOG", catalog),
                  mock.patch.object(source_pipeline.subprocess, "run", return_value=failed),
                  contextlib.redirect_stdout(io.StringIO())):
                with self.assertRaises(SystemExit) as raised:
                    source_pipeline.fetch()
            self.assertEqual(raised.exception.code, 1)
            manifest = json.loads((root / "sources/SOURCE_MANIFEST.json").read_text())
            self.assertEqual(manifest["synthetic"]["fetch_error"], "test timeout")
            self.assertFalse((root / "sources/raw/synthetic.html").exists())

    def test_existing_snapshot_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "sources/raw/synthetic.html"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"SYNTHETIC")
            catalog = {"synthetic": ("SYNTHETIC", "https://example.invalid/legal", "SYNTHETIC")}
            with (mock.patch.object(source_pipeline, "ROOT", root),
                  mock.patch.object(source_pipeline, "CATALOG", catalog),
                  mock.patch.object(source_pipeline.subprocess, "run") as network,
                  contextlib.redirect_stdout(io.StringIO())):
                source_pipeline.fetch()
            network.assert_not_called()
            manifest = json.loads((root / "sources/SOURCE_MANIFEST.json").read_text())
            self.assertIn("sha256", manifest["synthetic"])

    def test_repeat_fetch_keeps_matching_index_and_derived_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "sources/raw/synthetic.html"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"SYNTHETIC")
            catalog = {"synthetic": ("SYNTHETIC", "https://example.invalid/legal", "SYNTHETIC")}
            manifest_path = root / "sources/SOURCE_MANIFEST.json"
            manifest_path.write_text(json.dumps({
                "synthetic": {"sha256": source_pipeline.digest(raw.read_bytes()),
                              "url": catalog["synthetic"][1], "normalized_sha256": "indexed"},
                "derived": {"raw_path": "sources/raw/synthetic.html", "sha256": source_pipeline.digest(raw.read_bytes())},
            }))
            with (mock.patch.object(source_pipeline, "ROOT", root),
                  mock.patch.object(source_pipeline, "CATALOG", catalog),
                  mock.patch.object(source_pipeline.subprocess, "run") as network,
                  contextlib.redirect_stdout(io.StringIO())):
                source_pipeline.fetch()
            network.assert_not_called()
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["synthetic"]["normalized_sha256"], "indexed")
            self.assertEqual(manifest["derived"]["sha256"], source_pipeline.digest(raw.read_bytes()))

    def test_changed_snapshot_drops_stale_index_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "sources/raw/synthetic.html"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"NEW TEXT")
            catalog = {"synthetic": ("SYNTHETIC", "https://example.invalid/legal", "SYNTHETIC")}
            manifest_path = root / "sources/SOURCE_MANIFEST.json"
            manifest_path.write_text(json.dumps({"synthetic": {
                "sha256": source_pipeline.digest(b"OLD TEXT"), "url": catalog["synthetic"][1],
                "normalized_sha256": "stale", "effect_status": "已核验有效"}}))
            with (mock.patch.object(source_pipeline, "ROOT", root),
                  mock.patch.object(source_pipeline, "CATALOG", catalog),
                  contextlib.redirect_stdout(io.StringIO())):
                source_pipeline.fetch()
            entry = json.loads(manifest_path.read_text())["synthetic"]
            self.assertNotIn("normalized_sha256", entry)
            self.assertEqual(entry["effect_status"], "待逐项核验")

    def test_empty_cached_snapshot_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "sources/raw/synthetic.html"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"")
            catalog = {"synthetic": ("SYNTHETIC", "https://example.invalid/legal", "SYNTHETIC")}
            with (mock.patch.object(source_pipeline, "ROOT", root),
                  mock.patch.object(source_pipeline, "CATALOG", catalog),
                  contextlib.redirect_stdout(io.StringIO())):
                with self.assertRaises(SystemExit) as raised:
                    source_pipeline.fetch()
            self.assertEqual(raised.exception.code, 1)
            self.assertFalse(raw.exists())

    def test_incomplete_civil_code_build_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article = {"number": 1, "book": 1, "text": "SYNTHETIC", "sha256": "test"}
            with (mock.patch.object(source_pipeline, "ROOT", root),
                  mock.patch.object(source_pipeline, "parse", return_value=([article], [])),
                  contextlib.redirect_stdout(io.StringIO())):
                with self.assertRaises(SystemExit) as raised:
                    source_pipeline.build()
            self.assertEqual(raised.exception.code, 1)
            report = json.loads((root / "reports/SOURCE_INTEGRITY.json").read_text())
            self.assertFalse(report["automated_integrity_pass"])


if __name__ == "__main__":
    unittest.main()
