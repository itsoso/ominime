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
source "${SCRIPT_DIR}/native_python.sh"

OMINIME_TIMEZONE="${OMINIME_TIMEZONE:-America/New_York}"
OMINIME_DAY_TIMEZONE="${OMINIME_DAY_TIMEZONE:-Asia/Shanghai}"
OMINIME_STORAGE_TIMEZONE="${OMINIME_STORAGE_TIMEZONE:-$OMINIME_TIMEZONE}"

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
REQUIRED_VERSION="3.10"
PYTHON_BIN="$(ominime_select_python "$REQUIRED_VERSION")"
PYTHON_VERSION="$(ominime_python_version "$PYTHON_BIN")"
PYTHON_ARCH="$(ominime_python_arch "$PYTHON_BIN")"
echo -e "${GREEN}✓ Python $PYTHON_VERSION ($PYTHON_ARCH): $PYTHON_BIN${NC}"

# 创建虚拟环境
echo -e "${YELLOW}[2/5] 设置虚拟环境...${NC}"
cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    "$PYTHON_BIN" -m venv venv
    echo -e "${GREEN}✓ 虚拟环境已创建${NC}"
else
    ominime_require_native_python "$PROJECT_DIR/venv/bin/python"
    echo -e "${GREEN}✓ 虚拟环境已存在${NC}"
fi

source venv/bin/activate

# 安装依赖
echo -e "${YELLOW}[3/5] 安装依赖...${NC}"

# 检测是否需要使用镜像源（VPN/代理环境）
PIP_MIRROR=""
if [ "$USE_MIRROR" = "1" ] || [ "$USE_MIRROR" = "true" ]; then
    PIP_MIRROR="-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
    echo -e "${BLUE}使用清华镜像源${NC}"
fi

# 尝试安装，如果失败则自动切换镜像源
install_deps() {
    python -m pip install --upgrade pip $PIP_MIRROR -q 2>/dev/null && \
    python -m pip install -e . $PIP_MIRROR -q 2>/dev/null
}

if ! install_deps; then
    echo -e "${YELLOW}检测到网络问题，切换到清华镜像源...${NC}"
    PIP_MIRROR="-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
    
    # 临时禁用代理
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
    
    if ! install_deps; then
        echo -e "${RED}✗ 安装失败，请检查网络连接${NC}"
        echo ""
        echo "你可以尝试以下方法："
        echo "  1. 临时关闭 VPN/代理后重试"
        echo "  2. 手动安装: pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple"
        exit 1
    fi
fi

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

    <key>EnvironmentVariables</key>
    <dict>
        <key>TZ</key>
        <string>$OMINIME_TIMEZONE</string>
        <key>OMINIME_DAY_TIMEZONE</key>
        <string>$OMINIME_DAY_TIMEZONE</string>
        <key>OMINIME_STORAGE_TIMEZONE</key>
        <string>$OMINIME_STORAGE_TIMEZONE</string>
    </dict>
    
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
