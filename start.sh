#!/bin/bash
set -e
cd "$(dirname "$0")"

# Frontend deps
if [ ! -d frontend/node_modules ]; then
  echo ">>> Installing frontend dependencies..."
  cd frontend && npm install && cd ..
fi

# 清空 vite/postcss 缓存，防止中文路径下 tailwind 配置被旧缓存固化
rm -rf frontend/node_modules/.vite 2>/dev/null || true

# Python deps（首次需要；已装则秒跳）
if ! python3 -c "import fastapi, uvicorn, aiohttp, yaml, docx, openpyxl, pdfplumber, lxml" 2>/dev/null; then
  echo ">>> Installing Python dependencies..."
  pip3 install --quiet -e . || pip3 install --quiet --break-system-packages -e .
fi

echo ">>> Starting 规则梳理 Harness..."
echo "    后端: http://localhost:8765"
echo "    前端: http://localhost:5199"
echo ""

# 用 -m 启动，避免直接 python backend/app.py 导致 absolute import 失败
python3 -m backend.app
