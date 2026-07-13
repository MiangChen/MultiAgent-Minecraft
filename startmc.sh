#!/bin/sh
# 启动 Minecraft (HMCL 启动器)
echo "正在启动 Minecraft..."
DISPLAY="${DISPLAY:-:0}" nohup /home/ubuntu/opt/hmcl/start_hmcl.sh > /tmp/hmcl.log 2>&1 &
echo "HMCL 已启动 (PID: $!)"
echo "日志: /tmp/hmcl.log"
