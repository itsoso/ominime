#!/bin/bash
# OmniMe 每日导出定时任务安装脚本
# 安装 LaunchAgent，每天 23:30 自动导出到 Obsidian

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

# 配置
SERVICE_NAME="com.ominime.daily-export"
PLIST_PATH="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"
LOG_DIR="$HOME/.ominime/logs"
OMINIME_TIMEZONE="${OMINIME_TIMEZONE:-America/New_York}"
OMINIME_DAY_TIMEZONE="${OMINIME_DAY_TIMEZONE:-Asia/Shanghai}"
OMINIME_STORAGE_TIMEZONE="${OMINIME_STORAGE_TIMEZONE:-$OMINIME_TIMEZONE}"
EXPORT_SCRIPT="${SCRIPT_DIR}/daily_export.sh"

# 默认执行时间
HOUR="${OMINIME_EXPORT_HOUR:-23}"
MINUTE="${OMINIME_EXPORT_MINUTE:-30}"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║   ⏰ OmniMe 每日导出定时任务安装                          ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 检查导出脚本
if [ ! -f "$EXPORT_SCRIPT" ]; then
    echo -e "${RED}❌ 未找到导出脚本: $EXPORT_SCRIPT${NC}"
    exit 1
fi

# 确保导出脚本可执行
chmod +x "$EXPORT_SCRIPT"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 如果服务已存在，先停止并卸载
if launchctl list | grep -q "$SERVICE_NAME"; then
    echo -e "${YELLOW}⚠️  检测到已有定时任务，正在停止...${NC}"
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
        <string>${EXPORT_SCRIPT}</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>TZ</key>
        <string>${OMINIME_TIMEZONE}</string>
        <key>OMINIME_DAY_TIMEZONE</key>
        <string>${OMINIME_DAY_TIMEZONE}</string>
        <key>OMINIME_STORAGE_TIMEZONE</key>
        <string>${OMINIME_STORAGE_TIMEZONE}</string>
    </dict>
    
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>
    
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/daily_export_stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/daily_export_stderr.log</string>
    
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

# 加载服务
echo -e "${GREEN}🚀 加载定时任务...${NC}"
launchctl load "$PLIST_PATH"

# 检查服务状态
if launchctl list | grep -q "$SERVICE_NAME"; then
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   ✅ 每日导出定时任务已成功安装！                        ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   ⏰ 执行时间: 每天 ${HOUR}:${MINUTE}                               ║${NC}"
    echo -e "${GREEN}║   📁 导出目录: Obsidian/10_Sources/OmniMe/               ║${NC}"
    echo -e "${GREEN}║   📋 日志位置: ~/.ominime/logs/daily_export.log          ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "管理命令:"
    echo -e "  ${CYAN}手动执行${NC}: ${EXPORT_SCRIPT}"
    echo -e "  ${CYAN}查看日志${NC}: tail -f ~/.ominime/logs/daily_export.log"
    echo -e "  ${CYAN}卸载任务${NC}: ./scripts/uninstall_daily_export.sh"
else
    echo -e "${RED}❌ 定时任务加载失败${NC}"
    exit 1
fi
