#!/bin/bash
# 规则梳理工具 → tencent-gz 一键部署（由 Cowork 生成，可重复使用）
# 双击运行；进度写入 deploy_status.log
cd "$(dirname "$0")" || exit 1
LOG="$PWD/deploy_status.log"

{
  echo "== DEPLOY START $(date '+%F %T') =="
  echo "[1/3] rsync 同步代码到 tencent-gz:apps/rule-harness/ ..."
  rsync -az \
    --exclude .git \
    --exclude frontend/node_modules \
    --exclude frontend/dist \
    --exclude frontend/dist2 \
    --exclude data \
    --exclude .DS_Store \
    --exclude .playwright-mcp \
    --exclude .pytest_cache \
    --exclude rule_harness.egg-info \
    --exclude '测试样本' \
    --exclude .wrangler \
    --exclude .gstack \
    --exclude .devcontainer \
    --exclude cowork_deploy.command \
    --exclude deploy_status.log \
    ./ tencent-gz:apps/rule-harness/
  if [ $? -ne 0 ]; then echo "RSYNC_FAILED"; exit 1; fi
  # 纯代码目录用 --delete 镜像（本地删除的文件服务器同步删除）。
  # 只限 backend/ 与 frontend/src/：这两个目录不含服务器独有文件
  # （build-local.sh / data/ 在仓库根，绝不能对根目录用 --delete）。
  rsync -az --delete --exclude __pycache__ backend/ tencent-gz:apps/rule-harness/backend/ \
    && rsync -az --delete frontend/src/ tencent-gz:apps/rule-harness/frontend/src/
  if [ $? -ne 0 ]; then echo "RSYNC_MIRROR_FAILED"; exit 1; fi
  echo "RSYNC_OK"

  echo "[2/3] 服务器构建 build-local.sh（docker build，需几分钟，请勿关闭窗口）..."
  ssh tencent-gz 'bash ~/apps/rule-harness/build-local.sh'
  if [ $? -ne 0 ]; then echo "BUILD_FAILED"; exit 1; fi
  echo "BUILD_OK"

  echo "[3/3] 健康检查 https://api-rules.448898.xyz/health ..."
  sleep 5
  curl -fsS --max-time 30 https://api-rules.448898.xyz/health
  echo
  echo "== DEPLOY_DONE $(date '+%F %T') =="
} 2>&1 | tee "$LOG"
