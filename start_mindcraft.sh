#!/bin/sh

set -u

MINDCRAFT_DIR="/home/ubuntu/Desktop/mindcraft"
MINDSERVER_PORT="8080"
MINDCRAFT_URL="http://localhost:${MINDSERVER_PORT}"

cd "$MINDCRAFT_DIR" || {
  echo "找不到 Mindcraft 目录: $MINDCRAFT_DIR"
  exit 1
}

if ! command -v node >/dev/null 2>&1; then
  echo "未找到 node。请先安装 Node.js。"
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "未找到 node_modules。请先运行: npm install"
  exit 1
fi

echo
echo "================ Mindcraft ================"
echo "请确保 Minecraft 已打开世界并 Open to LAN"
echo "Mindcraft 后台: $MINDCRAFT_URL"
echo "停止: Ctrl+C"
echo "============================================"
echo

node main.js
