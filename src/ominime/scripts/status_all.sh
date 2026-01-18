#!/bin/bash
# OmniMe 全部服务状态查看脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

APP_SERVICE="com.ominime.app"
WEB_SERVICE="com.ominime.web"
EXPORT_SERVICE="com.ominime.daily-export"
LOG_DIR="$HOME/.ominime/logs"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║   📊 OmniMe 服务状态                                      ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 检查主应用状态
echo ""
echo -e "${CYAN}⌨️  主应用 (键盘监听)${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

APP_PLIST="$HOME/Library/LaunchAgents/${APP_SERVICE}.plist"
if [ ! -f "$APP_PLIST" ]; then
    echo -e "状态: ${RED}❌ 未安装${NC}"
else
    if launchctl list | grep -q "$APP_SERVICE"; then
        PID=$(launchctl list | grep "$APP_SERVICE" | awk '{print $1}')
        if [ "$PID" != "-" ] && [ -n "$PID" ]; then
            echo -e "状态: ${GREEN}🟢 运行中${NC} (PID: $PID)"
        else
            echo -e "状态: ${YELLOW}🟡 已加载但未运行${NC}"
        fi
    else
        echo -e "状态: ${RED}🔴 未运行${NC}"
    fi
fi

# 检查 Web 服务状态
echo ""
echo -e "${CYAN}🌐 Web 后台服务${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

WEB_PLIST="$HOME/Library/LaunchAgents/${WEB_SERVICE}.plist"
if [ ! -f "$WEB_PLIST" ]; then
    echo -e "状态: ${RED}❌ 未安装${NC}"
else
    if launchctl list | grep -q "$WEB_SERVICE"; then
        PID=$(launchctl list | grep "$WEB_SERVICE" | awk '{print $1}')
        if [ "$PID" != "-" ] && [ -n "$PID" ]; then
            echo -e "状态: ${GREEN}🟢 运行中${NC} (PID: $PID)"
            echo -e "地址: ${CYAN}http://127.0.0.1:8001${NC}"
            
            # 测试连接
            if curl -s --connect-timeout 2 "http://127.0.0.1:8001/api/stats/today" > /dev/null 2>&1; then
                echo -e "连接: ${GREEN}✅ 正常${NC}"
            else
                echo -e "连接: ${YELLOW}⚠️  无法连接${NC}"
            fi
        else
            echo -e "状态: ${YELLOW}🟡 已加载但未运行${NC}"
        fi
    else
        echo -e "状态: ${RED}🔴 未运行${NC}"
    fi
fi

# 检查每日导出定时任务状态
echo ""
echo -e "${CYAN}⏰ 每日导出定时任务${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

EXPORT_PLIST="$HOME/Library/LaunchAgents/${EXPORT_SERVICE}.plist"
if [ ! -f "$EXPORT_PLIST" ]; then
    echo -e "状态: ${RED}❌ 未安装${NC}"
else
    if launchctl list | grep -q "$EXPORT_SERVICE"; then
        echo -e "状态: ${GREEN}✅ 已安装${NC}"
        echo -e "执行时间: ${CYAN}每天 23:30${NC}"
    else
        echo -e "状态: ${YELLOW}🟡 已安装但未加载${NC}"
    fi
fi

# 日志信息
echo ""
echo -e "${CYAN}📋 日志文件${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "主应用日志: ${LOG_DIR}/app.log"
echo -e "主应用错误: ${LOG_DIR}/app.error.log"
echo -e "Web 日志:   ${LOG_DIR}/web.log"
echo -e "Web 错误:   ${LOG_DIR}/web.error.log"
echo -e "导出日志:   ${LOG_DIR}/daily_export.log"

# 管理命令
echo ""
echo -e "${CYAN}管理命令${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "安装全部: ./scripts/install_all.sh"
echo -e "卸载全部: ./scripts/uninstall_all.sh"
echo -e "实时日志: tail -f ~/.ominime/logs/*.log"
