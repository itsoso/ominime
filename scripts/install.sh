#!/bin/bash
# OmniMe 安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "🚀 OmniMe 安装脚本"
echo "=================="
echo ""

# 检查 Python 版本
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.10"

echo "📌 检查 Python 版本..."
if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ 需要 Python $REQUIRED_VERSION 或更高版本"
    echo "   当前版本: $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION"
echo ""

# 创建虚拟环境
echo "📌 创建虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ 虚拟环境已创建"
else
    echo "✅ 虚拟环境已存在"
fi
echo ""

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📌 安装依赖..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ 依赖安装完成"
echo ""

# 安装项目
echo "📌 安装 OmniMe..."
pip install -e . -q
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

