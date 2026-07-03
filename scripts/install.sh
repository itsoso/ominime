#!/bin/bash
# OmniMe 安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

source "${SCRIPT_DIR}/native_python.sh"

cd "$PROJECT_DIR"

echo "🚀 OmniMe 安装脚本"
echo "=================="
echo ""

# 检查 Python 版本
REQUIRED_VERSION="3.10"

echo "📌 检查 Python 版本..."
PYTHON_BIN="$(ominime_select_python "$REQUIRED_VERSION")"
PYTHON_VERSION="$(ominime_python_version "$PYTHON_BIN")"
PYTHON_ARCH="$(ominime_python_arch "$PYTHON_BIN")"
echo "✅ Python $PYTHON_VERSION ($PYTHON_ARCH): $PYTHON_BIN"
echo ""

# 创建虚拟环境
echo "📌 创建虚拟环境..."
if [ ! -d "venv" ]; then
    "$PYTHON_BIN" -m venv venv
    echo "✅ 虚拟环境已创建"
else
    ominime_require_native_python "$PROJECT_DIR/venv/bin/python"
    echo "✅ 虚拟环境已存在"
fi
echo ""

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📌 安装依赖..."
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
echo "✅ 依赖安装完成"
echo ""

# 安装项目
echo "📌 安装 OmniMe..."
python -m pip install -e . -q
echo "✅ OmniMe 安装完成"
echo ""

# 创建数据目录
echo "📌 创建数据目录..."
mkdir -p ~/.ominime/logs
echo "✅ 数据目录: ~/.ominime/"
echo ""

echo "=================="
echo "🎉 安装完成！"
echo ""
echo "使用方法:"
echo "  source venv/bin/activate  # 激活虚拟环境"
echo "  ominime                   # 启动 Menu Bar 应用"
echo "  ominime monitor           # 命令行监控"
echo "  ominime report            # 查看今日报告"
echo ""
echo "首次运行需要授予辅助功能权限："
echo "  系统偏好设置 → 隐私与安全性 → 辅助功能"
echo ""
