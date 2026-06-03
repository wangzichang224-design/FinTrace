#!/usr/bin/env python3
"""查找最新的评测产物路径。
Makefile 用它找到 showcase/frozen 等评测的输出目录，避免硬编码路径。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def find_latest_batch(runs_dir: str | Path) -> Path | None:
    """在 runs 目录下查找最新的 batch_result.json"""
    root = Path(runs_dir) / "runs"
    if not root.exists():
        return None
    candidates = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        batch_file = candidate / "batch_result.json"
        if batch_file.exists():
            return batch_file
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="查找最新的评测产物")
    parser.add_argument("runs_parent_dir", help="包含 runs/ 子目录的目录（如 runtime/showcase_eval）")
    parser.add_argument("--field", default="batch_result", choices=["batch_result", "traces", "dir"],
                        help="要查找的内容")
    args = parser.parse_args()

    batch = find_latest_batch(args.runs_parent_dir)
    if not batch:
        print(f"未在 {args.runs_parent_dir}/runs/ 下找到 batch_result.json", file=sys.stderr)
        sys.exit(1)

    if args.field == "batch_result":
        print(batch)
    elif args.field == "traces":
        traces = batch.parent / "traces.jsonl"
        print(traces if traces.exists() else "")
    elif args.field == "dir":
        print(batch.parent)


if __name__ == "__main__":
    main()
