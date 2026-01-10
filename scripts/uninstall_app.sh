#!/bin/bash
#
# OmniMe 卸载脚本
#
# 功能：
# 1. 停止运行的 OmniMe 进程
# 2. 移除开机启动
# 3. 可选：删除数据
#

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════╗"
echo "║       OmniMe 卸载程序                  ║"
echo "╚═══════════════════════════════════════╝"
echo -e "${NC}"

# 停止运行的进程
echo -e "${YELLOW}[1/3] 停止 OmniMe 进程...${NC}"
pkill -f "ominime" 2>/dev/null || true
echo -e "${GREEN}✓ 进程已停止${NC}"

# 移除开机启动
echo -e "${YELLOW}[2/3] 移除开机启动...${NC}"
PLIST_PATH="$HOME/Library/LaunchAgents/com.ominime.app.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo -e "${GREEN}✓ 开机启动已移除${NC}"
else
    echo -e "${GREEN}✓ 未设置开机启动${NC}"
fi

# 询问是否删除数据
echo ""
echo -e "${YELLOW}[3/3] 是否删除用户数据？${NC}"
echo "数据目录: $HOME/.ominime"
echo ""
read -p "删除所有数据？(y/N): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$HOME/.ominime"
    echo -e "${GREEN}✓ 数据已删除${NC}"
else
    echo -e "${GREEN}✓ 数据已保留${NC}"
fi

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       卸载完成！                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo "如需完全卸载，请手动删除项目目录。"
echo ""
