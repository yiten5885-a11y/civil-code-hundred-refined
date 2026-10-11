"""Program gate tests use a synthetic rule, never a real legal approval."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("answer", PROJECT / "skill/civil-code-plain-answers/scripts/answer.py")
answer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(answer)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        raw = self.root / "sources/raw/civil_code.html"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"SYNTHETIC TEST DATA ONLY")
        index = [{"number": n, "text": f"SYNTHETIC TEST ARTICLE {n}", "sha256": hashlib.sha256(f"SYNTHETICTESTARTICLE{n}".encode()).hexdigest()} for n in range(1, 1261)]
        index_path = self.root / "sources/normalized/civil_code.json"
        save(index_path, index)
        manifest = {"civil_code": {"effect_status": "已核验有效", "raw_path": "sources/raw/civil_code.html", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "normalized_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()}}
        save(self.root / "sources/SOURCE_MANIFEST.json", manifest)
        article = index[0]
        self.rule = {"id": "synthetic-one", "status": "approved", "scenario": "rent_deposit", "approved_text": "测试用固定文本，不构成法律结论。", "time_boundary": "SYNTHETIC", "region": "SYNTHETIC", "applicability": {"event_date_from": "2026-01-01", "event_date_through": "2026-12-31", "regions": ["SYNTHETIC"]}, "fact_pattern": {"deposit_returned": False}, "conditions": [], "exceptions": [], "required_facts": ["deposit_returned"], "unsupported_conclusions": [], "references": [{"source_id": "civil_code", "article": 1, "article_sha256": article["sha256"], "quote": "SYNTHETIC TEST ARTICLE 1"}]}
        self.rule_path = self.root / "rules/approved/synthetic-one.json"
        self.review_path = self.root / "review/synthetic-one.json"
        self.reseal()

    def tearDown(self):
        self.temp.cleanup()

    def reseal(self):
        save(self.rule_path, self.rule)
        save(self.review_path, {"decision": "approved", "reviewer": "SYNTHETIC_TEST_ONLY", "reviewer_role": "TEST_FIXTURE_NOT_A_PROFESSIONAL", "scope": "rent_deposit", "review_date": "2026-10-11", "rule_sha256": hashlib.sha256(self.rule_path.read_bytes()).hexdigest(), "source_manifest_sha256": hashlib.sha256((self.root / "sources/SOURCE_MANIFEST.json").read_bytes()).hexdigest()})

    def companion_fixture(self):
        raw = self.root / "sources/raw/synthetic_companion.html"
        raw.write_text("<p>第一条 SYNTHETIC COMPANION CLAUSE</p>")
        article = {"number": 1, "heading": "第一条", "text": "SYNTHETIC COMPANION CLAUSE", "sha256": hashlib.sha256(b"SYNTHETICCOMPANIONCLAUSE").hexdigest()}
        index_path = self.root / "sources/normalized/synthetic_companion.json"
        save(index_path, [article])
        manifest_path = self.root / "sources/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["synthetic_companion"] = {"effect_status": "已核验有效", "raw_path": "sources/raw/synthetic_companion.html", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "normalized_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()}
        save(manifest_path, manifest)
        self.rule["references"] = [{"source_id": "synthetic_companion", "article": 1, "article_sha256": article["sha256"], "locator": "第一条", "quote": "SYNTHETIC COMPANION CLAUSE"}]
        self.reseal()
        return index_path

    def ask(self, candidate=None, include_candidate=True, facts=None, history=None):
        query = {"question": "押金退还", "scenario": "rent_deposit", "rule_id": "synthetic-one"}
        if history is None:
            query["facts"] = {"event_date": "2026-10-11", "region": "SYNTHETIC", "deposit_returned": False} if facts is None else facts
        else:
            query["history"] = history
        if include_candidate:
            query["candidate_text"] = self.rule["approved_text"] if candidate is None else candidate
        return answer.handle(query, self.root)

    def assert_blocked(self):
        for _ in range(3):
            result = self.ask()
            self.assertNotEqual(result["status"], "ANSWER")
            self.assertNotIn(self.rule["approved_text"], result["text"])

    def test_synthetic_gate_passes(self):
        self.assertEqual(self.ask()["status"], "ANSWER")

    def test_explicit_scenario_mismatch_blocks_approved_text(self):
        base = {"scenario": "rent_deposit", "rule_id": "synthetic-one",
                "facts": {"event_date": "2026-10-11", "region": "SYNTHETIC", "deposit_returned": False},
                "candidate_text": self.rule["approved_text"]}
        for question in ("没有借条的转账怎么办？", "房东不退押金，还要我搬走怎么办？", "这笔钱怎么办？"):
            with self.subTest(question=question):
                result = answer.handle({**base, "question": question}, self.root)
                self.assertEqual(result["status"], "NEED_FACTS")
                self.assertNotIn(self.rule["approved_text"], result["text"])

    def test_cli_propagates_check_failure_and_keeps_limited_reply_successful(self):
        script = PROJECT / "skill/civil-code-plain-answers/scripts/answer.py"
        base = {"question": "押金退还", "scenario": "rent_deposit", "rule_id": "synthetic-one",
                "facts": {"event_date": "2026-10-11", "region": "SYNTHETIC", "deposit_returned": False}}

        def invoke(query):
            run = subprocess.run([sys.executable, str(script), "--root", str(self.root)],
                                 input=json.dumps(query, ensure_ascii=False), text=True,
                                 capture_output=True, check=False)
            return run.returncode, json.loads(run.stdout)

        ok_code, ok = invoke({**base, "candidate_text": self.rule["approved_text"]})
        self.assertEqual((ok_code, ok["status"]), (0, "ANSWER"))
        pending_code, pending = invoke({"question": "押金退还", "scenario": "rent_deposit"})
        self.assertEqual((pending_code, pending["status"]), (0, "PENDING_REVIEW"))
        failed_code, failed = invoke({**base, "candidate_text": "擅自改写"})
        self.assertEqual((failed_code, failed["status"]), (3, "CHECK_FAILED"))
        (self.root / "sources/normalized/civil_code.json").write_text("broken")
        error_code, error = invoke({**base, "candidate_text": self.rule["approved_text"]})
        self.assertEqual((error_code, error["status"]), (2, "SYSTEM_ERROR"))

    def test_malformed_input_returns_structured_system_error(self):
        script = PROJECT / "skill/civil-code-plain-answers/scripts/answer.py"
        for query in ([], {"question": ["押金"]}, {"question": "押金", "scenario": []}):
            with self.subTest(query=query):
                run = subprocess.run([sys.executable, str(script), "--root", str(self.root)],
                                     input=json.dumps(query, ensure_ascii=False), text=True,
                                     capture_output=True, check=False)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(json.loads(run.stdout)["status"], "SYSTEM_ERROR")

    def test_malformed_rule_and_manifest_fail_closed(self):
        save(self.rule_path, ["damaged rule"])
        result = self.ask()
        self.assertEqual(result["status"], "SYSTEM_ERROR")
        self.reseal()
        manifest_path = self.root / "sources/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["civil_code"] = ["damaged source"]
        save(manifest_path, manifest)
        self.reseal()
        result = self.ask()
        self.assertEqual(result["status"], "SYSTEM_ERROR")

    def test_candidate_missing_stops_before_display(self):
        self.assertEqual(self.ask(include_candidate=False)["status"], "CANDIDATE_REQUIRED")

    def test_candidate_changed_stops_before_display(self):
        for text in ("", "擅自添加法律判断", self.rule["approved_text"] + "额外结论"):
            result = self.ask(candidate=text)
            self.assertEqual(result["status"], "CHECK_FAILED")
            self.assertNotIn(self.rule["approved_text"], result["text"])

    def test_wrong_article_hash_blocks_three_times(self):
        self.rule["references"][0]["article_sha256"] = "0" * 64
        self.reseal()
        self.assert_blocked()

    def test_wrong_quote_blocks(self):
        self.rule["references"][0]["quote"] = "NOT IN ARTICLE"
        self.reseal()
        self.assert_blocked()

    def test_companion_article_index_is_checked(self):
        self.companion_fixture()
        self.assertEqual(self.ask()["status"], "ANSWER")
        self.rule["references"][0]["locator"] = "第二条"
        self.reseal()
        self.assert_blocked()

    def test_missing_companion_index_blocks(self):
        index_path = self.companion_fixture()
        index_path.unlink()
        self.assert_blocked()

    def test_missing_citation_blocks_three_times(self):
        self.rule["references"] = []
        self.reseal()
        self.assert_blocked()

    def test_retired_rule_blocks_three_times(self):
        self.rule["status"] = "disabled"
        self.reseal()
        self.assert_blocked()

    def test_missing_source_blocks_three_times(self):
        (self.root / "sources/raw/civil_code.html").unlink()
        self.assert_blocked()

    def test_corrupt_index_blocks_three_times(self):
        (self.root / "sources/normalized/civil_code.json").write_text("broken")
        self.assert_blocked()

    def test_tampered_review_blocks_three_times(self):
        self.rule["approved_text"] = "擅自改写"
        save(self.rule_path, self.rule)
        self.assert_blocked()

    def test_changed_source_manifest_invalidates_review(self):
        manifest_path = self.root / "sources/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["metadata_change"] = "review must be repeated"
        save(manifest_path, manifest)
        self.assert_blocked()

    def test_candidates_never_approved(self):
        self.rule_path.unlink()
        save(self.root / "rules/candidates/synthetic-one.json", self.rule)
        self.assert_blocked()

    def test_required_fact_is_requested(self):
        self.rule["required_facts"] = ["deposit_returned", "handover_complete"]
        self.reseal()
        self.assertEqual(self.ask()["status"], "NEED_FACTS")

    def test_missing_event_date_blocks(self):
        facts = {"region": "SYNTHETIC", "deposit_returned": False}
        self.assertEqual(self.ask(facts=facts)["status"], "NEED_FACTS")

    def test_outside_reviewed_date_or_region_blocks(self):
        for facts in (
            {"event_date": "2025-12-31", "region": "SYNTHETIC", "deposit_returned": False},
            {"event_date": "2026-10-11", "region": "OTHER", "deposit_returned": False},
        ):
            self.assertEqual(self.ask(facts=facts)["status"], "PENDING_REVIEW")

    def test_corrected_user_fact_rechecks_rule(self):
        history = [
            {"role": "user", "facts": {"event_date": "2026-10-11", "region": "SYNTHETIC", "deposit_returned": False}},
            {"role": "assistant", "content": "测试回复"},
            {"role": "user", "facts": {"deposit_returned": True}},
        ]
        self.assertEqual(self.ask(history=history)["status"], "PENDING_REVIEW")
        history.append({"role": "user", "facts": {"deposit_returned": False}})
        self.assertEqual(self.ask(history=history)["status"], "ANSWER")

    def test_unreviewed_extra_fact_blocks(self):
        facts = {"event_date": "2026-10-11", "region": "SYNTHETIC", "deposit_returned": False, "damage_claimed": True}
        self.assertEqual(self.ask(facts=facts)["status"], "PENDING_REVIEW")

    def test_assistant_cannot_insert_user_fact(self):
        history = [
            {"role": "user", "facts": {"event_date": "2026-10-11", "region": "SYNTHETIC"}},
            {"role": "assistant", "facts": {"deposit_returned": False}},
        ]
        self.assertEqual(self.ask(history=history)["status"], "NEED_FACTS")

    def test_missing_applicability_envelope_blocks(self):
        self.rule.pop("applicability")
        self.reseal()
        self.assert_blocked()

    def test_urgent_preempts_legal_work(self):
        result = answer.handle({"question": "他现在持刀要杀我，我怎么分房？"}, self.root)
        self.assertEqual(result["status"], "URGENT")

    def test_active_assault_preempts_property_question(self):
        result = answer.handle({"question": "我现在被打，押金怎么拿回？"}, self.root)
        self.assertEqual(result["status"], "URGENT")

    def test_landlord_deposit_question_routes_to_deposit(self):
        result = answer.handle({"question": "房东不退押金怎么办？"}, self.root)
        self.assertEqual(result["status"], "PENDING_REVIEW")

    def test_unsupported_calculation(self):
        result = answer.handle({"question": "帮我算精确分房比例"}, self.root)
        self.assertEqual(result["status"], "OUT_OF_SCOPE")


if __name__ == "__main__":
    unittest.main()
