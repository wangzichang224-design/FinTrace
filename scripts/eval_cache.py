"""评测缓存管理。

避免同一冻结数据集在同一模式下重复跑全量评测。
基于数据集内容的哈希做缓存键，数据集变更后自动失效。

用法:
  python -m scripts.eval_cache check <dataset_dir> <llm_mode>
  python -m scripts.eval_cache mark <dataset_dir> <llm_mode>
  python -m scripts.eval_cache clear
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


CACHE_DIR = Path(os.environ.get("FINTRACE_EVAL_CACHE", "runtime/.eval_cache"))


def dataset_hash(dataset_dir: str | Path) -> str:
    """计算冻结数据集的内容哈希（只包含 ground_truth.json 和 dataset_manifest.json）。"""
    root = Path(dataset_dir)
    hasher = hashlib.sha256()
    for name in ["ground_truth.json", "dataset_manifest.json"]:
        path = root / name
        if path.exists():
            hasher.update(path.read_bytes())
        # 如果文件不存在则不参与哈希（旧数据集可能没有 manifest）
    return hasher.hexdigest()[:16]


def cache_key(dataset_dir: str | Path, llm_mode: str) -> str:
    """生成缓存键: {数据集哈希}_{llm_mode}"""
    return f"{dataset_hash(dataset_dir)}_{llm_mode}"


def check(dataset_dir: str | Path, llm_mode: str) -> bool:
    """检查缓存是否存在。"""
    key = cache_key(dataset_dir, llm_mode)
    cache_file = CACHE_DIR / f"{key}.done"
    exists = cache_file.exists()
    if exists:
        print(f"  [缓存命中] {dataset_dir} ({llm_mode}) → 跳过")
    else:
        print(f"  [缓存未命中] {dataset_dir} ({llm_mode}) → 需要运行")
    return exists


def mark(dataset_dir: str | Path, llm_mode: str) -> None:
    """写入缓存标记。"""
    key = cache_key(dataset_dir, llm_mode)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.done"
    cache_file.write_text(
        json.dumps({"dataset": str(dataset_dir), "llm_mode": llm_mode, "hash": dataset_hash(dataset_dir)}, indent=2),
        encoding="utf-8",
    )
    print(f"  [缓存写入] {cache_file}")


def clear() -> None:
    """清除所有评测缓存。"""
    if CACHE_DIR.exists():
        import shutil
        shutil.rmtree(CACHE_DIR)
        print(f"  [缓存清除] {CACHE_DIR}")
    else:
        print(f"  [缓存] 不存在，无需清除")


def main() -> None:
    parser = argparse.ArgumentParser(description="FinTrace 评测缓存管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_parser = sub.add_parser("check", help="检查缓存是否存在")
    check_parser.add_argument("dataset_dir", help="冻结数据集目录")
    check_parser.add_argument("--llm-mode", default="mock", choices=["mock", "deepseek"])

    mark_parser = sub.add_parser("mark", help="写入缓存标记")
    mark_parser.add_argument("dataset_dir", help="冻结数据集目录")
    mark_parser.add_argument("--llm-mode", default="mock", choices=["mock", "deepseek"])

    sub.add_parser("clear", help="清除所有缓存")

    args = parser.parse_args()

    if args.cmd == "check":
        sys.exit(0 if check(args.dataset_dir, args.llm_mode) else 1)
    elif args.cmd == "mark":
        mark(args.dataset_dir, args.llm_mode)
    elif args.cmd == "clear":
        clear()


if __name__ == "__main__":
    main()
