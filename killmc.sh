#!/bin/sh
# 杀死所有 mindcraft 和 MC 服务器相关进程

echo "正在关闭所有 Mindcraft / Minecraft 进程..."

# mindcraft node 进程
pkill -f "node.*main\.js" 2>/dev/null
pkill -f "init_agent\.js" 2>/dev/null

# MC 服务器
pkill -f "server-1.20.4\.jar" 2>/dev/null

sleep 2

# 检查是否还有残留，强制杀
pkill -9 -f "node.*main\.js" 2>/dev/null
pkill -9 -f "init_agent\.js" 2>/dev/null
pkill -9 -f "server-1.20.4\.jar" 2>/dev/null

echo "完成。"
