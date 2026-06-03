# FinTrace 自动化编排
# 用法:  make <target>
#
# 平台自动检测：Windows (PowerShell/CMD) 使用 python, Linux/macOS 使用 python3
#
#   make ci            完整检查（快检 → 回归 → 前端验证）
#   make quickcheck    快检（AST + 单元测试）
#   make regression    全量回归评测（冻结集）
#   make showcase      Showcase DeepSeek 评测
#   make show          Showcase DeepSeek 评测（不缓存）
#   make external-eval 外部评测适配器
#   make frontend      前端验收
#   make docker        使用 Docker Compose 运行
#   make setup         首次开发环境设置
#   make list          列出所有可用 target

.PHONY: ci quickcheck check-ast check-unit regression showcase show external-eval frontend clean list setup docker docker-eval

# ─── 配置 ───────────────────────────────────────────────

SHELL := /bin/bash

# 自动检测 Python 命令
ifeq ($(OS),Windows_NT)
    PYTHON := python
    IS_WINDOWS := 1
else
    PYTHON := python3
    IS_WINDOWS := 0
endif

FINTRACE_ROOT := $(shell pwd)
RUNTIME_ROOT := $(FINTRACE_ROOT)/runtime

# ─── 完整 CI 管道 ──────────────────────────────────────

ci: quickcheck showcase regression external-eval
	@echo "=== FinTrace CI 全部通过 ==="
	@echo "提示：前端验收需要 Streamlit 已在运行，执行: make frontend"

# ─── 快检 ──────────────────────────────────────────────

quickcheck: check-ast check-unit
	@echo "=== 快检全部通过 ==="

check-ast:
	@echo "[1/2] AST 语法检查..."
	@$(PYTHON) scripts/check_ast.py
	@echo "[1/2] AST 语法检查通过"

check-unit:
	@echo "[2/2] 单元测试..."
	@$(PYTHON) -m unittest discover -s tests -v
	@echo "[2/2] 单元测试通过"

# ─── Showcase DeepSeek 评测 ─────────────────────────────

showcase:
	@echo "=== Showcase DeepSeek 评测 ==="
	@$(PYTHON) scripts/run_pipeline.py --step showcase-deepseek --runtime-dir "$(RUNTIME_ROOT)"
	@echo "=== Showcase DeepSeek 评测完成 ==="

show:
	@echo "=== Showcase DeepSeek 评测（不缓存）==="
	@$(PYTHON) scripts/run_pipeline.py --step showcase-deepseek --no-cache --runtime-dir "$(RUNTIME_ROOT)"
	@echo "=== Showcase DeepSeek 评测完成 ==="

# ─── 全量回归 ──────────────────────────────────────────

regression: quickcheck
	@echo "=== 全量回归 ==="
	@$(PYTHON) scripts/run_pipeline.py --step regression --runtime-dir "$(RUNTIME_ROOT)"
	@echo "=== 全量回归完成 ==="

# ─── 外部评测适配器 ─────────────────────────────────────

external-eval:
	@echo "=== 外部评测适配器 ==="
	@$(PYTHON) scripts/run_pipeline.py --step external-eval --runtime-dir "$(RUNTIME_ROOT)"
	@echo "=== 外部评测完成 ==="

# ─── 前端验收 ──────────────────────────────────────────

frontend:
	@echo "=== 前端验收 ==="
	@$(PYTHON) scripts/check_frontend.py --url http://localhost:8509
	@echo "=== 前端验收通过 ==="

# ─── Docker 环境 ───────────────────────────────────────

docker:
	@echo "=== 使用 Docker Compose 启动 FinTrace ==="
	docker compose up fintrace-frontend

docker-eval:
	@echo "=== 使用 Docker Compose 运行评测 ==="
	docker compose up fintrace-eval

docker-test:
	@echo "=== 使用 Docker Compose 运行测试 ==="
	docker compose up fintrace-test

docker-cli:
	@echo "=== 使用 Docker Compose 运行 CLI ==="
	@docker compose run --rm fintrace-cli $(filter-out $@,$(MAKECMDGOALS))

docker-build:
	@echo "=== 构建 Docker 镜像 ==="
	docker compose build

# ─── 开发环境设置 ───────────────────────────────────────

setup:
ifneq ($(IS_WINDOWS),1)
	@echo "=== 设置 Linux/macOS 开发环境 ==="
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt && pip install -r requirements-eval.txt
	@echo "激活: source .venv/bin/activate"
else
	@echo "=== 设置 Windows 开发环境 ==="
	@echo "请运行 setup.bat"
endif

# ─── 工具 ──────────────────────────────────────────────

clean:
	@echo "清理评测缓存..."
	@$(PYTHON) -m scripts.eval_cache clear
	@echo "已清除缓存"

list:
	@echo "可用 target:"
	@echo "  make ci             完整检查：快检 -> Showcase -> 回归 -> 外部评测"
	@echo "  make quickcheck     快检：AST + 单元测试"
	@echo "  make showcase       Showcase DeepSeek 评测（缓存）"
	@echo "  make show           Showcase DeepSeek 评测（不缓存）"
	@echo "  make regression     全量回归（含快检前置，缓存）"
	@echo "  make external-eval  外部评测适配器"
	@echo "  make frontend       前端验收（需先启动 Streamlit）"
	@echo "  make docker         使用 Docker 启动 Web 界面"
	@echo "  make docker-eval    使用 Docker 运行评测"
	@echo "  make docker-test    使用 Docker 运行测试"
	@echo "  make docker-cli     使用 Docker 运行 CLI 命令"
	@echo "  make docker-build   构建 Docker 镜像（无缓存）"
	@echo "  make setup          首次开发环境设置"
	@echo "  make clean          清除缓存"
