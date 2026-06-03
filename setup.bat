@echo off
REM FinTrace Windows 开发环境设置
REM 用法: 双击运行，或在终端执行 setup.bat

echo === FinTrace Windows 开发环境设置 ===
echo.

if not exist ".venv_windows" (
    echo [1/3] 创建虚拟环境...
    python -m venv .venv_windows
) else (
    echo [1/3] 虚拟环境已存在，跳过。
)

echo [2/3] 安装依赖...
call .venv_windows\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-eval.txt

echo.
echo [3/3] 可选: 复制 .env.example 到 .env
if not exist ".env" (
    copy .env.example .env >nul 2>&1
    echo 已创建 .env，请填入 DEEPSEEK_API_KEY（如需 LLM 增强）
) else (
    echo .env 已存在，跳过。
)

echo.
echo === 设置完成 ===
echo.
echo 启动方式:
echo   1. 运行 Streamlit:  Start_FinTrace_Frontend.cmd
echo   2. 或手动启动:      streamlit run streamlit_app.py --server.port=8509
echo.
echo 激活虚拟环境: .venv_windows\Scripts\activate
echo.
pause
