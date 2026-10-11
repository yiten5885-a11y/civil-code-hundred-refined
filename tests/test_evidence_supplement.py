"""Private Qwen draft generation must stay local and reject unsupported citations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from generate_evidence_supplement import (archive_partial, local_endpoint, prompt_for,
                                          known_error_codes, third_turn_correction_binding,
                                          validated_card)  # noqa: E402
from supplement_inputs import load_specs  # noqa: E402


class EvidenceSupplementTest(unittest.TestCase):
    def test_known_deposit_inversion_is_rejected_without_claiming_general_semantic_validation(self):
        spec = {"evidence": [{"source_id": "housing_lease", "article": 10}],
                "required_citations": [{"source_id": "housing_lease", "article": 10}]}
        card = {"plain_explanation": "待核查", "conditions": ["扣减押金需符合约定或无正当理由"],
                "exceptions": ["待核查"], "unknown_facts": ["日期"], "unsupported": ["不推断结果"],
                "changes_from_prior": ["补充原文"],
                "cited_sources": [{"source_id": "housing_lease", "article": 10}],
                "dialogue": [{"user": "合同没写扣减情形", "assistant": "需核查"},
                             {"user": "我还没退房", "assistant": "需核查"},
                             {"user": "更正：我之前说「合同没写扣减情形」不对，实际是「合同写了扣减情形」。",
                              "assistant": "扣减仍须无正当理由"}]}
        self.assertEqual(known_error_codes(card, "rent_deposit"), ["deposit_justification_inverted"])
        with self.assertRaisesRegex(ValueError, "已知错误表达"):
            validated_card(json.dumps(card, ensure_ascii=False), "rent_deposit", spec,
                           require_correction_binding=True)
        card["conditions"] = ["扣减理由待核查"]
        card["dialogue"][2]["assistant"] = "仍需核查扣减理由"
        self.assertEqual(known_error_codes(card, "rent_deposit"), [])
        self.assertEqual(validated_card(json.dumps(card, ensure_ascii=False), "rent_deposit", spec,
                                        require_correction_binding=True), card)

    def test_failed_responses_survive_retries_with_same_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "scene.partial.txt"
            with patch("generate_evidence_supplement.now", return_value="2026-10-11T10:00:00+00:00"):
                partial.write_bytes(b"first")
                first = archive_partial(partial)
                partial.write_bytes(b"second")
                second = archive_partial(partial)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), b"first")
            self.assertEqual(second.read_bytes(), b"second")
            self.assertFalse(partial.exists())

    def test_local_endpoint_only(self):
        self.assertEqual(local_endpoint("http://[::1]:11434"), "http://[::1]:11434/api/chat")
        self.assertEqual(local_endpoint("127.0.0.1:11434"), "http://127.0.0.1:11434/api/chat")
        for host in ("https://127.0.0.1:11434", "http://example.com:11434",
                     "http://127.0.0.1:11434/other", "http://user:secret@localhost:11434"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                local_endpoint(host)

    def test_selection_rejects_unlisted_required_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan").mkdir()
            (root / "plan/SUPPLEMENT_EVIDENCE.json").write_text(json.dumps({"scenarios": {
                "rent_deposit": {"focus": "押金", "evidence": [{"source_id": "civil_code", "article": 703}],
                                 "required_citations": [{"source_id": "housing_lease", "article": 10}]}
            }}))
            with self.assertRaisesRegex(ValueError, "必引条文不在输入中"):
                load_specs(root)

    def test_candidate_needs_required_citation(self):
        spec = {"evidence": [{"source_id": "civil_code", "article": 703},
                              {"source_id": "housing_lease", "article": 10}],
                "required_citations": [{"source_id": "housing_lease", "article": 10}]}
        card = {"plain_explanation": "待审核", "conditions": ["待核查"], "exceptions": ["待核查"],
                "unknown_facts": ["日期"], "unsupported": ["不推断结果"],
                "changes_from_prior": ["补充条文"],
                "cited_sources": [{"source_id": "civil_code", "article": 703}],
                "dialogue": [{"user": "问题", "assistant": "待核查"}] * 2 +
                            [{"user": "更正：前提不同。", "assistant": "待核查"}]}
        with self.assertRaisesRegex(ValueError, "遗漏必引条文"):
            validated_card(json.dumps(card, ensure_ascii=False), "rent_deposit", spec)
        card["cited_sources"].append({"source_id": "housing_lease", "article": 10})
        self.assertEqual(validated_card(json.dumps(card, ensure_ascii=False), "rent_deposit", spec), card)

    def test_new_prompt_names_every_required_citation(self):
        evidence = [{"source_id": "civil_code", "article": 1077, "source_title": "民法典", "text": "测试原文"},
                    {"source_id": "marriage_registration_2025", "article": 16,
                     "source_title": "登记条例", "text": "测试原文"}]
        required = [{"source_id": "civil_code", "article": 1077},
                    {"source_id": "marriage_registration_2025", "article": 16}]
        prompt = prompt_for("divorce_agreement_registration", "节点核查", "旧候选", evidence, required)
        self.assertIn("cited_sources 至少包含：civil_code 第1077条、marriage_registration_2025 第16条", prompt)
        self.assertIn("dialogue 必须恰好三轮", prompt)
        self.assertNotIn("每个数组最多两项", prompt)

    def test_dialogue_article_mention_must_be_cited(self):
        spec = {"evidence": [{"source_id": "civil_code", "article": 1077},
                             {"source_id": "marriage_registration_2025", "article": 14}],
                "required_citations": [{"source_id": "civil_code", "article": 1077}]}
        card = {"plain_explanation": "2025条例待核查", "conditions": ["需核对"], "exceptions": ["需核对"],
                "unknown_facts": ["日期"], "unsupported": ["不推断结果"],
                "changes_from_prior": ["补充条文"],
                "cited_sources": [{"source_id": "civil_code", "article": 1077}],
                "dialogue": [{"user": "请问第十四条？", "assistant": "依据条例第十四条仍须核查前提。"}] * 2 +
                            [{"user": "更正：申请日期不同。", "assistant": "依据条例第十四条仍须核查前提。"}]}
        with self.assertRaisesRegex(ValueError, "未列入引用.*14"):
            validated_card(json.dumps(card, ensure_ascii=False), "divorce_agreement_registration", spec)
        card["cited_sources"].append({"source_id": "marriage_registration_2025", "article": 14})
        self.assertEqual(validated_card(json.dumps(card, ensure_ascii=False), "divorce_agreement_registration", spec), card)

    def test_third_turn_must_signal_a_correction(self):
        spec = {"evidence": [{"source_id": "civil_code", "article": 713}],
                "required_citations": [{"source_id": "civil_code", "article": 713}]}
        card = {"plain_explanation": "待审核", "conditions": ["待核查"], "exceptions": ["待核查"],
                "unknown_facts": ["原因"], "unsupported": ["不推断结果"],
                "changes_from_prior": ["补充条文"],
                "cited_sources": [{"source_id": "civil_code", "article": 713}],
                "dialogue": [{"user": "漏水了", "assistant": "请核对原因"},
                             {"user": "房东没修", "assistant": "请核对通知"},
                             {"user": "还有别的办法吗？", "assistant": "需要核查"}]}
        with self.assertRaisesRegex(ValueError, "第三轮用户没有明确更正前提"):
            validated_card(json.dumps(card, ensure_ascii=False), "rent_repair", spec)
        card["dialogue"][2]["user"] = "更正：漏水是我忘关水龙头造成的。"
        self.assertEqual(validated_card(json.dumps(card, ensure_ascii=False), "rent_repair", spec), card)

    def test_new_dialogue_must_withdraw_a_quoted_prior_user_fact(self):
        spec = {"evidence": [{"source_id": "civil_code", "article": 675}],
                "required_citations": [{"source_id": "civil_code", "article": 675}]}
        card = {"plain_explanation": "待审核", "conditions": ["待核查"], "exceptions": ["待核查"],
                "unknown_facts": ["日期"], "unsupported": ["不推断结果"],
                "changes_from_prior": ["补充条文"],
                "cited_sources": [{"source_id": "civil_code", "article": 675}],
                "dialogue": [{"user": "借款已到期。", "assistant": "请核对记录"},
                             {"user": "没有展期协议。", "assistant": "请核对日期"},
                             {"user": "更正：其实双方签了展期协议。", "assistant": "需重新核对"}]}
        self.assertFalse(third_turn_correction_binding(card))
        with self.assertRaisesRegex(ValueError, "未绑定先前用户事实"):
            validated_card(json.dumps(card, ensure_ascii=False), "loan_overdue", spec,
                           require_correction_binding=True)
        card["dialogue"][2]["user"] = "更正：我之前说「没有展期协议」不对，实际是「双方签了展期协议」。"
        self.assertTrue(third_turn_correction_binding(card))
        self.assertEqual(validated_card(json.dumps(card, ensure_ascii=False), "loan_overdue", spec,
                                        require_correction_binding=True), card)
        card["dialogue"][2]["user"] = "更正：我之前说「没有借条」不对，实际是「双方签了展期协议」。"
        self.assertFalse(third_turn_correction_binding(card))

    def test_new_prompt_requires_explicit_prior_quote(self):
        evidence = [{"source_id": "civil_code", "article": 675,
                     "source_title": "民法典", "text": "测试原文"}]
        prompt = prompt_for("loan_overdue", "节点核查", "旧候选", evidence,
                            [{"source_id": "civil_code", "article": 675}],
                            require_correction_binding=True)
        self.assertIn("旧事实须逐字出现在前两轮", prompt)
        self.assertIn("更正：我之前说「旧事实」不对", prompt)


if __name__ == "__main__":
    unittest.main()
