#!/bin/bash
# OmniMe Web 服务状态查看脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SERVICE_NAME="com.ominime.web"
PLIST_PATH="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"
LOG_DIR="$HOME/.ominime/logs"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║   📊 OmniMe Web 服务状态                                  ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 检查 plist 文件
if [ ! -f "$PLIST_PATH" ]; then
    echo -e "${RED}❌ 服务未安装${NC}"
    echo "运行 ./scripts/install_web.sh 进行安装"
    exit 1
fi

echo -e "${GREEN}✅ 服务已安装${NC}"
echo ""

# 检查服务运行状态
if launchctl list | grep -q "$SERVICE_NAME"; then
    PID=$(launchctl list | grep "$SERVICE_NAME" | awk '{print $1}')
    if [ "$PID" != "-" ] && [ -n "$PID" ]; then
        echo -e "状态: ${GREEN}🟢 运行中${NC} (PID: $PID)"
        
        # 检查端口
        PORT=$(grep -A1 "<string>-p</string>" "$PLIST_PATH" | tail -1 | sed 's/.*<string>\(.*\)<\/string>.*/\1/')
        HOST=$(grep -A1 "<string>-H</string>" "$PLIST_PATH" | tail -1 | sed 's/.*<string>\(.*\)<\/string>.*/\1/')
        
        echo -e "地址: ${CYAN}http://${HOST}:${PORT}${NC}"
        
        # 测试连接
        if curl -s --connect-timeout 2 "http://${HOST}:${PORT}/api/health" > /dev/null 2>&1; then
            echo -e "连接: ${GREEN}✅ 正常${NC}"
        else
            echo -e "连接: ${YELLOW}⚠️  无法连接（可能正在启动中）${NC}"
        fi
    else
        echo -e "状态: ${YELLOW}🟡 已加载但未运行${NC}"
    fi
else
    echo -e "状态: ${RED}🔴 未运行${NC}"
fi

echo ""
echo -e "日志文件:"
echo -e "  标准输出: ${CYAN}${LOG_DIR}/web.log${NC}"
echo -e "  错误日志: ${CYAN}${LOG_DIR}/web.error.log${NC}"

# 显示最近日志
if [ -f "$LOG_DIR/web.log" ]; then
    echo ""
    echo -e "${CYAN}最近日志 (最后 5 行):${NC}"
    tail -5 "$LOG_DIR/web.log" 2>/dev/null | sed 's/^/  /'
fi

echo ""
echo -e "管理命令:"
echo -e "  ${CYAN}重启服务${NC}: launchctl unload $PLIST_PATH && launchctl load $PLIST_PATH"
echo -e "  ${CYAN}停止服务${NC}: launchctl unload $PLIST_PATH"
echo -e "  ${CYAN}实时日志${NC}: tail -f $LOG_DIR/web.log"
