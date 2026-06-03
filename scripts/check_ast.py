#!/usr/bin/env python3
"""检查项目内所有 Python 文件的 AST 语法正确性。"""
from __future__ import annotations

import ast
import pathlib
import sys


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    errors: list[str] = []

    for pyfile in sorted(root.rglob("*.py")):
        # 跳过不影响项目的目录
        skip_parts = {"runtime", "__pycache__", ".git", ".mypy_cache", ".pytest_cache", "venv", ".venv", "node_modules"}
        if skip_parts & set(pyfile.parts):
            continue
        if not pyfile.read_text(encoding="utf-8", errors="ignore").strip():
            continue
        try:
            ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
        except SyntaxError as e:
            errors.append(f"  FAIL: {pyfile.relative_to(root)}: {e}")

    if errors:
        print("\n".join(errors))
        print(f"  {len(errors)} 个文件语法错误")
        sys.exit(1)

    print(f"  所有 Python 文件语法正确")


if __name__ == "__main__":
    main()
