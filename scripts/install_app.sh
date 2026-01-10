#!/bin/bash
#
# OmniMe 安装脚本
#
# 功能：
# 1. 安装 Python 依赖
# 2. 设置开机启动
# 3. 启动应用
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════╗"
echo "║       OmniMe 安装程序                  ║"
echo "║       macOS 输入追踪系统               ║"
echo "╚═══════════════════════════════════════╝"
echo -e "${NC}"

# 检查 Python 版本
echo -e "${YELLOW}[1/5] 检查 Python 版本...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
    echo -e "${GREEN}✓ Python $PYTHON_VERSION 已安装${NC}"
else
    echo -e "${RED}✗ 需要 Python 3.10 或更高版本${NC}"
    echo "  当前版本: $PYTHON_VERSION"
    echo "  请安装 Python 3.10+: https://www.python.org/downloads/"
    exit 1
fi

# 创建虚拟环境
echo -e "${YELLOW}[2/5] 设置虚拟环境...${NC}"
cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ 虚拟环境已创建${NC}"
else
    echo -e "${GREEN}✓ 虚拟环境已存在${NC}"
fi

source venv/bin/activate

# 安装依赖
echo -e "${YELLOW}[3/5] 安装依赖...${NC}"
pip install --upgrade pip -q
pip install -e . -q
echo -e "${GREEN}✓ 依赖安装完成${NC}"

# 获取 ominime 命令路径
OMINIME_PATH="$PROJECT_DIR/venv/bin/ominime"

# 设置数据目录
DATA_DIR="$HOME/.ominime"
mkdir -p "$DATA_DIR"

# 设置开机启动
echo -e "${YELLOW}[4/5] 设置开机启动...${NC}"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.ominime.app.plist"

mkdir -p "$LAUNCH_AGENTS_DIR"

# 生成 plist 文件
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ominime.app</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>$OMINIME_PATH</string>
        <string>app</string>
    </array>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <false/>
    
    <key>StandardOutPath</key>
    <string>$DATA_DIR/ominime.log</string>
    
    <key>StandardErrorPath</key>
    <string>$DATA_DIR/ominime.error.log</string>
    
    <key>ProcessType</key>
    <string>Interactive</string>
    
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
</dict>
</plist>
EOF

# 加载 LaunchAgent
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo -e "${GREEN}✓ 开机启动已设置${NC}"

# 启动应用
echo -e "${YELLOW}[5/5] 启动 OmniMe...${NC}"

# 检查辅助功能权限
echo ""
echo -e "${YELLOW}⚠️  重要提示：${NC}"
echo "OmniMe 需要「辅助功能」权限才能监听键盘输入。"
echo ""
echo "请按以下步骤授权："
echo "  1. 打开「系统偏好设置」→「隐私与安全性」→「辅助功能」"
echo "  2. 点击左下角的锁图标解锁"
echo "  3. 找到并勾选 Terminal.app 或您使用的终端应用"
echo ""

# 启动应用
"$OMINIME_PATH" app &

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       安装完成！                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo "使用方法："
echo "  • 菜单栏图标 ⌨️ - 点击查看统计和设置"
echo "  • ominime web   - 启动 Web 后台管理"
echo "  • ominime monitor - 命令行监控模式"
echo "  • ominime report  - 查看今日报告"
echo ""
echo "数据存储位置: $DATA_DIR"
echo ""
