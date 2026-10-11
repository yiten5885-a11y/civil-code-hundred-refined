#!/usr/bin/env python3
"""Generate the twelve unreviewed Qwen cards sequentially, skipping completed scenes."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

from generate_one_candidate import ARTICLES
from local_ollama import local_endpoint

ROOT = Path(__file__).resolve().parents[1]
ONE = ROOT / "scripts/generate_one_candidate.py"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="重生成全部场景并保存旧版")
    parser.add_argument("--upgrade-dialogue", action="store_true", help="仅重生成旧式三句答复，保存旧版")
    parser.add_argument("--host", help="本机 Ollama 回环地址；默认由单场景脚本读取 OLLAMA_HOST")
    args = parser.parse_args()
    if args.host:
        try:
            local_endpoint(args.host)
        except ValueError as exc:
            parser.exit(2, f"本地模型地址无效：{exc}\n")
    for scene in ARTICLES:
        target = ROOT / "rules/candidates" / f"{scene}.json"
        upgrade = False
        if target.is_file() and args.upgrade_dialogue:
            card = json.loads(target.read_text())["card"]
            dialogue = card.get("dialogue", [])
            upgrade = not (len(dialogue) == 3 and all(isinstance(turn, dict) for turn in dialogue))
        if target.is_file() and not args.replace and not upgrade:
            print(scene, "already saved", flush=True)
            continue
        print(scene, "starting", flush=True)
        command = [sys.executable, str(ONE), scene]
        if args.host:
            command += ["--host", args.host]
        if args.replace or upgrade:
            command.append("--replace")
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
