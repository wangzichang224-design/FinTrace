#!/usr/bin/env python3
"""FinTrace CI 管道编排脚本。

Makefile 的每步实际逻辑都在这里执行，Makefile 只充当"入口"。
这样避免了在 Makefile 里写复杂的多行 shell 脚本。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    """打印并执行命令。"""
    cmd_str = " ".join(str(a) for a in args)
    print(f"  $ {cmd_str}")
    return subprocess.run(args, cwd=PROJECT_ROOT, **kwargs)


def step_showcase_deepseek(runtime_dir: Path, no_cache: bool = False) -> None:
    """运行 Showcase DeepSeek 评测。"""
    dataset = PROJECT_ROOT / "datasets" / "showcase_fintrace_v1"
    output = runtime_dir / "showcase_eval"
    llm_mode = "deepseek"

    if no_cache:
        print("  [跳过缓存检查]")
    else:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.eval_cache", "check", str(dataset), "--llm-mode", llm_mode],
            cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            print("  [缓存命中] Showcase DeepSeek 评测跳过")
            return

    print("  运行 Showcase DeepSeek 评测...")

    # 用 subprocess.run 执行 cli 命令
    result = run(
        sys.executable, "cli.py", "eval-frozen",
        str(dataset),
        "--output-root", str(output),
        "--llm-mode", llm_mode,
    )
    if result.returncode != 0:
        print(f"  FAIL: Showcase DeepSeek 评测失败 (exit={result.returncode})")
        sys.exit(1)

    # 写入缓存
    if not no_cache:
        subprocess.run(
            [sys.executable, "-m", "scripts.eval_cache", "mark", str(dataset), "--llm-mode", llm_mode],
            cwd=PROJECT_ROOT,
            check=True,
        )

    # 显示摘要
    batch_dir = next((output / "runs").iterdir(), None)
    if batch_dir and (batch_dir / "batch_metrics.json").exists():
        import json
        metrics = json.loads((batch_dir / "batch_metrics.json").read_text(encoding="utf-8"))
        print(f"  案件数: {metrics.get('case_count')}")
        print(f"  决策分布: {metrics.get('decision_counts')}")
        print(f"  风险分布: {metrics.get('risk_counts')}")
        print(f"  节点失败数: {metrics.get('node_failure_count')}")


def step_regression(runtime_dir: Path) -> None:
    """运行全量回归。"""
    datasets = [
        ("fintrace-redteam-v1", PROJECT_ROOT / "datasets" / "fintrace-redteam-v1"),
        ("red_attack_v1", PROJECT_ROOT / "datasets" / "red_attack_v1"),
        ("showcase_fintrace_v1", PROJECT_ROOT / "datasets" / "showcase_fintrace_v1"),
    ]
    output_base = runtime_dir / "regression_check"

    for name, dataset_path in datasets:
        print(f"\n  [回归] {name}...")
        result = subprocess.run(
            [sys.executable, "-m", "scripts.eval_cache", "check", str(dataset_path), "--llm-mode", "mock"],
            cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            print(f"  [缓存命中] {name} 跳过")
            continue

        run(
            sys.executable, "cli.py", "eval-frozen",
            str(dataset_path),
            "--output-root", str(output_base / name.replace("-", "_")),
        )

        subprocess.run(
            [sys.executable, "-m", "scripts.eval_cache", "mark", str(dataset_path), "--llm-mode", "mock"],
            cwd=PROJECT_ROOT,
            check=True,
        )


def step_external_eval(runtime_dir: Path) -> None:
    """运行外部评测适配器。"""
    showcase_runs = (runtime_dir / "showcase_eval" / "runs")
    if not showcase_runs.exists():
        print("  FAIL: 未找到 showcase_eval 产物，先运行 make showcase")
        sys.exit(1)

    # 找到最新的
    candidates = sorted(showcase_runs.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    batch_result = None
    for c in candidates:
        br = c / "batch_result.json"
        if br.exists():
            batch_result = br
            break

    if not batch_result:
        print("  FAIL: 未找到 batch_result.json")
        sys.exit(1)

    traces = batch_result.parent / "traces.jsonl"
    output_dir = runtime_dir / "external_eval" / "showcase"

    print(f"  使用 batch: {batch_result}")
    if traces.exists():
        print(f"  使用 traces: {traces}")

    args = [
        sys.executable, "scripts/external_eval_adapter.py",
        str(batch_result),
        "--output-dir", str(output_dir),
    ]
    if traces.exists():
        args.extend(["--traces", str(traces)])

    result = run(*args)
    if result.returncode != 0:
        print(f"  WARN: 外部评测适配器退出码 {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="FinTrace CI 管道")
    parser.add_argument("--step", required=True,
                        choices=["showcase-deepseek", "regression", "external-eval"])
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--no-cache", action="store_true",
                        help="忽略缓存强制重新运行")
    args = parser.parse_args()

    runtime_dir = Path(args.runtime_dir)

    if args.step == "showcase-deepseek":
        step_showcase_deepseek(runtime_dir, no_cache=args.no_cache)
    elif args.step == "regression":
        step_regression(runtime_dir)
    elif args.step == "external-eval":
        step_external_eval(runtime_dir)


if __name__ == "__main__":
    main()
