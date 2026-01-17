#!/bin/bash
# OmniMe 全部服务安装脚本
# 安装主应用（键盘监听）+ Web 后台服务

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║   🚀 OmniMe 全部后台服务安装                              ║"
echo "║                                                          ║"
echo "║   将安装:                                                ║"
echo "║   1. ⌨️  主应用 (键盘监听/输入追踪)                       ║"
echo "║   2. 🌐 Web 后台 (仪表板/API)                            ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo ""
echo -e "${CYAN}[1/2] 安装主应用服务...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"$SCRIPT_DIR/install_app.sh"

echo ""
echo -e "${CYAN}[2/2] 安装 Web 服务...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"$SCRIPT_DIR/install_web.sh"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                          ║${NC}"
echo -e "${GREEN}║   🎉 全部服务安装完成！                                  ║${NC}"
echo -e "${GREEN}║                                                          ║${NC}"
echo -e "${GREEN}║   ⌨️  主应用: 已启动键盘监听                              ║${NC}"
echo -e "${GREEN}║   🌐 Web: http://127.0.0.1:8001                          ║${NC}"
echo -e "${GREEN}║                                                          ║${NC}"
echo -e "${GREEN}║   所有服务将在开机时自动启动                             ║${NC}"
echo -e "${GREEN}║   关闭终端后服务会持续运行                               ║${NC}"
echo -e "${GREEN}║                                                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "管理命令:"
echo -e "  ${CYAN}查看状态${NC}: ./scripts/status_all.sh"
echo -e "  ${CYAN}卸载全部${NC}: ./scripts/uninstall_all.sh"
