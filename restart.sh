#!/bin/bash
# 一键重启脚本：杀旧进程 → 清前端缓存 → 启动后端 + 前端
# 用法：bash restart.sh   或   ./restart.sh

set -e
cd "$(dirname "$0")"

echo ">>> 1/4 停止旧的 backend / vite 进程..."
pkill -f "backend.app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
pkill -f "uvicorn.*backend.app" 2>/dev/null || true
sleep 1

echo ">>> 2/4 清前端 vite 缓存..."
rm -rf frontend/node_modules/.vite 2>/dev/null || true

echo ">>> 3/4 检查依赖..."
if [ ! -d frontend/node_modules ]; then
  echo "    安装前端依赖..."
  (cd frontend && npm install)
fi
if ! python3 -c "import fastapi, uvicorn, aiohttp, yaml, docx, openpyxl, pdfplumber, lxml" 2>/dev/null; then
  echo "    安装 Python 依赖..."
  pip3 install --quiet -e . 2>/dev/null || pip3 install --quiet --break-system-packages -e .
fi

echo ">>> 4/4 启动..."
echo "    后端: http://localhost:8765"
echo "    前端: http://localhost:5199"
echo "    Ctrl+C 同时停止两者"
echo ""
exec python3 -m backend.app
