#!/bin/bash
# OmniMe 主应用（键盘监听）安装脚本
# 将主应用安装为 macOS LaunchAgent（后台服务）

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "${PROJECT_ROOT}/scripts/native_python.sh"

# 配置
SERVICE_NAME="com.ominime.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"
LOG_DIR="$HOME/.ominime/logs"
PYTHON_PATH="${PROJECT_ROOT}/venv/bin/python"
OMINIME_TIMEZONE="${OMINIME_TIMEZONE:-America/New_York}"
OMINIME_DAY_TIMEZONE="${OMINIME_DAY_TIMEZONE:-Asia/Shanghai}"
OMINIME_STORAGE_TIMEZONE="${OMINIME_STORAGE_TIMEZONE:-$OMINIME_TIMEZONE}"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║   ⌨️  OmniMe 主应用后台服务安装                           ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 检查 Python 虚拟环境
if [ ! -f "$PYTHON_PATH" ]; then
    echo -e "${RED}❌ 未找到 Python 虚拟环境: $PYTHON_PATH${NC}"
    echo "请先运行: cd ${PROJECT_ROOT} && python -m venv venv && source venv/bin/activate && pip install -e ."
    exit 1
fi

ominime_require_native_python "$PYTHON_PATH"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 如果服务已存在，先停止并卸载
if launchctl list | grep -q "$SERVICE_NAME"; then
    echo -e "${YELLOW}⚠️  检测到已有服务运行，正在停止...${NC}"
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

# 创建 LaunchAgent plist 文件
echo -e "${GREEN}📝 创建 LaunchAgent 配置...${NC}"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${SERVICE_NAME}</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>-m</string>
        <string>ominime.main</string>
        <string>app</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>${PROJECT_ROOT}/src</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>PYTHONPATH</key>
        <string>${PROJECT_ROOT}/src</string>
        <key>TZ</key>
        <string>${OMINIME_TIMEZONE}</string>
        <key>OMINIME_DAY_TIMEZONE</key>
        <string>${OMINIME_DAY_TIMEZONE}</string>
        <key>OMINIME_STORAGE_TIMEZONE</key>
        <string>${OMINIME_STORAGE_TIMEZONE}</string>
    </dict>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/app.log</string>
    
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/app.error.log</string>
    
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# 加载服务
echo -e "${GREEN}🚀 启动后台服务...${NC}"
launchctl load "$PLIST_PATH"

# 等待服务启动
sleep 2

# 检查服务状态
if launchctl list | grep -q "$SERVICE_NAME"; then
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   ✅ 主应用服务已成功安装并启动！                        ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   ⌨️  键盘监听已开始记录                                  ║${NC}"
    echo -e "${GREEN}║   📋 日志位置: ~/.ominime/logs/app.log                   ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   服务将在开机时自动启动                                 ║${NC}"
    echo -e "${GREEN}║   关闭 Cursor/终端后服务会持续运行                       ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "管理命令:"
    echo -e "  ${CYAN}停止服务${NC}: launchctl unload ~/Library/LaunchAgents/${SERVICE_NAME}.plist"
    echo -e "  ${CYAN}启动服务${NC}: launchctl load ~/Library/LaunchAgents/${SERVICE_NAME}.plist"
    echo -e "  ${CYAN}查看日志${NC}: tail -f ~/.ominime/logs/app.log"
    echo -e "  ${CYAN}卸载服务${NC}: ./scripts/uninstall_app.sh"
else
    echo -e "${RED}❌ 服务启动失败，请检查日志: ${LOG_DIR}/app.error.log${NC}"
    exit 1
fi
