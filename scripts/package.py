#!/usr/bin/env python3
"""Build the clearly labelled alpha Agent Skill archive without local law snapshots."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0-alpha"
SKILL = ROOT / "skill/civil-code-plain-answers"
ARCHIVE = ROOT / f"dist/civil-code-plain-answers-{VERSION}.zip"
SKILLHUB_DIR = ROOT / "dist/skillhub/civil-code-plain-answers"
SKILLHUB_ARCHIVE = ROOT / f"dist/civil-code-plain-answers-skillhub-{VERSION}.zip"


def archive_directory(folder: Path, archive: Path):
    files = sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zi = zipfile.ZipInfo(path.relative_to(folder.parent).as_posix(), (2026, 10, 11, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, path.read_bytes())
    return files


def main():
    assert (SKILL / "SKILL.md").is_file()
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    files = archive_directory(SKILL, ARCHIVE)
    if SKILLHUB_DIR.exists():
        shutil.rmtree(SKILLHUB_DIR)
    shutil.copytree(SKILL, SKILLHUB_DIR, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    skillhub_md = SKILLHUB_DIR / "SKILL.md"
    source = skillhub_md.read_text()
    marker = "license: MIT\n"
    assert source.count(marker) == 1
    source = source.replace(marker, marker + f"slug: civil-code-plain-answers\ndisplayName: 民法典百炼白话问答（未审定内测）\ndisplay_name: 民法典百炼白话问答（未审定内测）\nversion: {VERSION}\nsummary: 中国大陆借贷、租房与婚姻财产问题的事实整理和来源指引；法律解释尚未开放。\ntags: [民法典, 法律资料, 事实梳理]\ndescription_zh: 整理借贷、租房和婚姻财产问题的事实与官方来源；法律结论待专业复核。\ndescription_en: Organize facts and official sources for mainland China lending, residential leases, and marital property; legal conclusions await professional review.\nauthor: 民法典百炼白话问答项目贡献者\n", 1)
    skillhub_md.write_text(source)
    archive_directory(SKILLHUB_DIR, SKILLHUB_ARCHIVE)
    manifest = {
        "version": VERSION,
        "status": "未获法律专业复核；法律解释未开放",
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "archive_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
        "files": {p.relative_to(SKILL.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "skillhub_archive": str(SKILLHUB_ARCHIVE.relative_to(ROOT)),
        "skillhub_archive_sha256": hashlib.sha256(SKILLHUB_ARCHIVE.read_bytes()).hexdigest(),
        "skillhub_note": "使用 SkillHub 教程的 slug/displayName/version/summary/tags/license，并补齐 WorkBuddy 开放平台的 description_zh/description_en/author/display_name；是否通过平台审核仍待实际提交验证",
    }
    (ROOT / "dist/PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"archive": str(ARCHIVE), "sha256": manifest["archive_sha256"], "skillhub_archive": str(SKILLHUB_ARCHIVE), "skillhub_sha256": manifest["skillhub_archive_sha256"], "files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
