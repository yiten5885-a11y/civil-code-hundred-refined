"""Check the standalone ZIP without project sources or local Qwen."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "dist/civil-code-plain-answers-0.1.0-alpha.zip"


def main():
    with zipfile.ZipFile(PACKAGE) as bundle:
        names = bundle.namelist()
        assert "civil-code-plain-answers/SKILL.md" in names
        assert "civil-code-plain-answers/scripts/answer.py" in names
        assert all(not any(part in name.split("/") for part in ("raw", "normalized", "candidates", "approved", "review")) for name in names)
        with tempfile.TemporaryDirectory() as temp:
            bundle.extractall(temp)
            script = Path(temp) / "civil-code-plain-answers/scripts/answer.py"
            result = subprocess.run([sys.executable, str(script)], input=json.dumps({"question": "押金还没退", "scenario": "rent_deposit"}), text=True, capture_output=True, check=True)
            response = json.loads(result.stdout)
            assert response["status"] == "PENDING_REVIEW", response
            assert "法律判断" in response["text"]
    print("isolated alpha package: PENDING_REVIEW; no local law or candidate data")


if __name__ == "__main__":
    main()
