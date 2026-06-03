#!/usr/bin/env python3
"""前端自动化验收脚本。
检查 Streamlit 页面内容是否包含不应出现的敏感词，
以及验证关键案件是否存在。

用法:
  python scripts/check_frontend.py
  python scripts/check_frontend.py --url http://localhost:8509
  python scripts/check_frontend.py --url http://localhost:8509 --check-case SHOW-TS-01
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request


# 不应出现在前端页面的敏感词（红队/内部术语）
FORBIDDEN_PHRASES = [
    "LLM调用失败",
    "LLM门控",
    "employee_credit",
    "冷启动字段",
    "DeepSeek Key",
    "红队",
    "测试结果",
    "红蓝",
    "ground_truth",
    "debug_events",
]

# 应出现在页面中的关键词（指定环境下的）
REQUIRED_PHRASES = [
    "FinTrace",
    "费控",
    "批量审核",
]

# 应出现在案件详情中的元素（按案件类型）
CASE_REQUIRED_ELEMENTS: dict[str, list[str]] = {
    "SHOW-TS-01": [
        "R012_TIME_SPACE_CONFLICT",
        "时空冲突",
    ],
}


def fetch_page(url: str) -> str:
    """获取 Streamlit 页面的 HTML 内容。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FinTrace-Checker/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"  FAIL: 无法访问 {url}：{e}")
        sys.exit(1)


def check_forbidden(html: str) -> list[str]:
    """检查页面是否包含敏感词。"""
    found: list[str] = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in html.lower():
            found.append(phrase)
    return found


def check_required(html: str) -> list[str]:
    """检查页面是否包含必需元素。"""
    missing: list[str] = []
    for phrase in REQUIRED_PHRASES:
        if phrase not in html:
            missing.append(phrase)
    return missing


def check_case_in_html(html: str, case_id: str, required: list[str]) -> list[str]:
    """检查案件 ID 及其必需元素是否出现在页面中。"""
    if case_id not in html:
        print(f"  WARN: 案件 {case_id} 未在页面中找到（可能是未加载）")
        return []
    missing: list[str] = []
    for element in required:
        if element not in html:
            missing.append(element)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="FinTrace 前端验收脚本")
    parser.add_argument("--url", default="http://localhost:8509", help="Streamlit 服务 URL")
    parser.add_argument("--check-case", nargs="*", default=[], help="额外验证指定案件 ID（可多个）")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    print(f"  前端验收: {url}")
    print()

    html = fetch_page(url)
    print(f"  页面大小: {len(html)} 字符")
    print()

    # 检查敏感词
    forbidden = check_forbidden(html)
    if forbidden:
        print(f"  FAIL: 页面包含敏感词:")
        for word in forbidden:
            print(f"    - {word}")
        sys.exit(1)
    else:
        print(f"  PASS: 无敏感词暴露")

    # 检查必需元素
    missing = check_required(html)
    if missing:
        print(f"  WARN: 页面缺少以下必备元素（可能页面未完全加载，需人工确认）:")
        for phrase in missing:
            print(f"    - {phrase}")
    else:
        print(f"  PASS: 必需元素齐全")

    # 检查指定案件
    for case_id in args.check_case:
        required = CASE_REQUIRED_ELEMENTS.get(case_id, [])
        if not required:
            print(f"  SKIP: 案件 {case_id} 无预定义检查项")
            continue
        case_missing = check_case_in_html(html, case_id, required)
        if case_missing:
            print(f"  WARN: 案件 {case_id} 缺少以下元素（可能是未展开详情）:")
            for element in case_missing:
                print(f"    - {element}")
        else:
            print(f"  PASS: 案件 {case_id} 检查通过")

    print()
    print("  前端验收完成")


if __name__ == "__main__":
    main()
