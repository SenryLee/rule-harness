#!/bin/bash
set -e
cd "$(dirname "$0")"

# Frontend deps
if [ ! -d frontend/node_modules ]; then
  echo ">>> Installing frontend dependencies..."
  cd frontend && npm install && cd ..
fi

echo ">>> Starting 规则梳理 Harness..."
echo "    后端: http://localhost:8765"
echo "    前端: http://localhost:5199"
echo ""

python backend/app.py
