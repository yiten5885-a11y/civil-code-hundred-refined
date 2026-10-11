"""Check the SkillHub ZIP standalone: no project sources, no local Qwen, no legal conclusions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
PACKAGE = ROOT / f"dist/civil-code-plain-answers-skillhub-{VERSION}.zip"


def main():
    with zipfile.ZipFile(PACKAGE) as bundle:
        names = bundle.namelist()
        for required in (
            "civil-code-plain-answers/SKILL.md",
            "civil-code-plain-answers/LICENSE.txt",
            "civil-code-plain-answers/scripts/answer.py",
            "civil-code-plain-answers/references/release-manifest.json",
            "civil-code-plain-answers/references/rules.json",
        ):
            assert required in names, f"缺少 {required}"
        forbidden = {"tests", "tools", "evidence", "sources", "raw", "normalized",
                     "candidates", "approved", "review"}
        assert all(not any(part in forbidden for part in name.split("/")) for name in names), names

        with tempfile.TemporaryDirectory() as temp:
            bundle.extractall(temp)
            skill = Path(temp) / "civil-code-plain-answers"
            script = skill / "scripts/answer.py"
            result = subprocess.run(
                [sys.executable, str(script), "--question", "押金还没退，我该先看什么？"],
                text=True, capture_output=True,
            )
            assert result.returncode == 0, result.stderr
            response = json.loads(result.stdout)
            assert response["render_contract"]["allow_host_append"] is False
            assert response["text"].strip()
            kinds = {b["kind"] for b in response["blocks"]}
            assert "LEGAL_EXPLANATION" not in kinds, kinds
            caps = {c["id"]: c["state"] for c in response["capability_results"]}
            for cap in ("LEGAL01", "LEGAL02"):
                assert caps.get(cap) in (None, "NOT_ENABLED"), caps
            manifest = json.loads((skill / "references/release-manifest.json").read_text())
            assert manifest["profile"] == "D1"
            assert "LEGAL01" not in manifest["enabled_capabilities"]

    print("skillhub package: D1 navigation only; no legal explanation, no local law/candidate data")


if __name__ == "__main__":
    main()
