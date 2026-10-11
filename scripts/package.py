#!/usr/bin/env python3
"""Build the D1 Agent Skill archives.

- 完整包：`skill/` 下除 `__pycache__`、`evidence` 之外的全部文件；
- SkillHub 上架包：只保留运行时子集（SKILL.md、LICENSE.txt、config/、references/、scripts/）。

slug / displayName / version / summary / tags / license 直接写在 SKILL.md 的 frontmatter 里，
本脚本不再注入；`skillhub publish` 读取的就是这些字段。
"""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
SKILL = ROOT / "skill/civil-code-plain-answers"
DIST = ROOT / "dist"
ARCHIVE = DIST / f"civil-code-plain-answers-{VERSION}.zip"
SKILLHUB_ARCHIVE = DIST / f"civil-code-plain-answers-skillhub-{VERSION}.zip"

# 只进入上架包的运行子集；tests/、tools/、sources/、evidence/ 不随公开包分发。
PUBLISH_ROOTS = ("SKILL.md", "LICENSE.txt", "config", "references", "scripts")
SKIP_DIRS = {"__pycache__", "evidence", ".git", ".github"}


def collect(folder: Path, roots=None):
    targets = [folder / r for r in roots] if roots else [folder]
    out = []
    for target in targets:
        if target.is_file():
            out.append(target)
            continue
        for path in target.rglob("*"):
            if not path.is_file() or path.suffix == ".pyc":
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(folder).parts):
                continue
            out.append(path)
    return sorted(set(out))


def archive(files, folder: Path, archive_path: Path):
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zi = zipfile.ZipInfo(path.relative_to(folder.parent).as_posix(), (2026, 10, 11, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, path.read_bytes())


def main():
    assert (SKILL / "SKILL.md").is_file()
    DIST.mkdir(parents=True, exist_ok=True)

    full = collect(SKILL)
    archive(full, SKILL, ARCHIVE)

    publish = collect(SKILL, PUBLISH_ROOTS)
    archive(publish, SKILL, SKILLHUB_ARCHIVE)

    manifest = {
        "version": VERSION,
        "profile": "D1",
        "status": "未获法律专业复核；法律解释能力（LEGAL01/LEGAL02）未开放",
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "archive_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
        "skillhub_archive": str(SKILLHUB_ARCHIVE.relative_to(ROOT)),
        "skillhub_archive_sha256": hashlib.sha256(SKILLHUB_ARCHIVE.read_bytes()).hexdigest(),
        "skillhub_files": [p.relative_to(SKILL).as_posix() for p in publish],
        "files": {p.relative_to(SKILL).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in full},
        "note": "SkillHub 上架包只含运行时子集；元数据直接来自 SKILL.md frontmatter。",
    }
    (DIST / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "archive": manifest["archive"],
        "sha256": manifest["archive_sha256"],
        "skillhub_archive": manifest["skillhub_archive"],
        "skillhub_sha256": manifest["skillhub_archive_sha256"],
        "files": len(full),
        "skillhub_files": len(publish),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
