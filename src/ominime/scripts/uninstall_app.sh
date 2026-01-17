#!/bin/bash
# OmniMe 主应用服务卸载脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SERVICE_NAME="com.ominime.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║   🗑️  OmniMe 主应用后台服务卸载                           ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 检查服务是否存在
if [ ! -f "$PLIST_PATH" ]; then
    echo -e "${YELLOW}⚠️  主应用服务未安装${NC}"
    exit 0
fi

# 停止并卸载服务
echo -e "${YELLOW}⏹️  停止服务...${NC}"
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# 删除 plist 文件
echo -e "${YELLOW}🗑️  删除配置文件...${NC}"
rm -f "$PLIST_PATH"

echo ""
echo -e "${GREEN}✅ 主应用后台服务已成功卸载${NC}"
echo ""
echo -e "${CYAN}提示:${NC} 日志文件保留在 ~/.ominime/logs/ 目录"
