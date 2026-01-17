#!/bin/bash
# OmniMe 完整启动脚本 - 同时启动 Web 服务和菜单栏应用

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# 激活虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 获取 ominime 命令路径
OMINIME_PATH=$(which ominime)
if [ -z "$OMINIME_PATH" ]; then
    echo "错误: 找不到 ominime 命令"
    exit 1
fi

# 设置日志目录
LOG_DIR="$HOME/.ominime"
mkdir -p "$LOG_DIR"

# 启动 Web 服务（后台运行）
echo "启动 Web 服务..."
"$OMINIME_PATH" web > "$LOG_DIR/web.log" 2>&1 &
WEB_PID=$!

# 等待 Web 服务启动
sleep 2

# 检查 Web 服务是否成功启动
if ! kill -0 $WEB_PID 2>/dev/null; then
    echo "警告: Web 服务启动失败"
else
    echo "Web 服务已启动 (PID: $WEB_PID)"
fi

# 启动菜单栏应用（前台运行，这样 LaunchAgent 可以监控它）
echo "启动菜单栏应用..."
"$OMINIME_PATH" app

# 如果菜单栏应用退出，也停止 Web 服务
if kill -0 $WEB_PID 2>/dev/null; then
    echo "停止 Web 服务..."
    kill $WEB_PID 2>/dev/null
fi
