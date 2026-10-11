#!/usr/bin/env python3
"""Create a private reviewer handoff ZIP; never include it in public skill packages."""
import json
from pathlib import Path
import zipfile

from audit_candidates import main as audit
from audit_supplements import main as audit_supplements
from build_review_worksheet import main as build_worksheet
from build_acceptance_worksheet import main as build_acceptance_worksheet
from generate_one_candidate import ARTICLES

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "dist/民法典百炼-专业复核候选包.zip"


def main():
    audit()
    audit_supplements()
    result = json.loads((ROOT / "reports/CANDIDATE_AUDIT.json").read_text())
    supplement_report = json.loads((ROOT / "reports/SUPPLEMENT_AUDIT.json").read_text())["supplements"]
    if not result["structure_pass"] or result["saved_scenes"] != len(ARTICLES):
        raise SystemExit("十二个候选未通过完整结构检查，暂不打包")
    build_worksheet()
    build_acceptance_worksheet()
    files = [ROOT / "rules/candidates" / f"{scene}.json" for scene in ARTICLES]
    files += [ROOT / path for path in (
        "docs/法律专业复核交接.md", "rules/candidates/REVIEW_FLAGS.md",
        "rules/candidates/REVIEW_WORKSHEET.md",
        "tests/LEGAL_ACCEPTANCE_WORKSHEET.md",
        "plan/SOURCE_COVERAGE.md",
        "plan/SUPPLEMENT_EVIDENCE.json",
        "skill/civil-code-plain-answers/references/scenarios.md",
        "sources/SOURCE_MANIFEST.json", "reports/SOURCE_INTEGRITY.json",
        "reports/SOURCE_HASH_AUDIT.json",
        "reports/COMPANION_EXTRACTION.json", "reports/MARRIAGE_REGISTRATION_CROSSCHECK.json", "reports/LOAN_LEASE_EXTRACTION.json",
        "reports/LENDING_CROSSCHECK.json", "reports/SOURCE_SEARCH_SMOKE.json", "reports/CANDIDATE_AUDIT.json",
        "reports/SUPPLEMENT_AUDIT.json", "reports/EFFECT_PRECHECK.md",
        "reports/ENVIRONMENT_PUBLIC.json",
    )]
    supplements = ROOT / "rules/candidates/supplements"
    files += sorted(supplements.glob("*.json")) + sorted(supplements.glob("*.REVIEW.md"))
    files += sorted(path for path in (supplements / "versions").glob("*") if path.is_file())
    # Private review material only: exact local excerpts/full normalized sources are
    # useful for checking omissions and are excluded from Git and public packages.
    files += sorted((ROOT / "sources/normalized").glob("*.json"))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), (2026, 10, 11, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())
    print(json.dumps({"bundle": str(TARGET.relative_to(ROOT)), "files": len(files),
                      "candidate_count": len(ARTICLES),
                      "supplement_structure_failures": [scene for scene, item in supplement_report.items()
                                                        if not item["structure_pass"]],
                      "supplement_known_error_failures": [scene for scene, item in supplement_report.items()
                                                          if not item.get("known_error_screen_pass", True)],
                      "status": "未获专业审核"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
