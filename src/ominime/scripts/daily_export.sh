#!/bin/bash
# OmniMe 每日自动导出脚本
# 导出当天的输入记录和 AI 分析到 Obsidian

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# 配置
PYTHON_PATH="${PROJECT_ROOT}/venv/bin/python"
LOG_DIR="$HOME/.ominime/logs"
LOG_FILE="$LOG_DIR/daily_export.log"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 记录开始时间
echo "========================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始每日导出..." >> "$LOG_FILE"

# 检查 Python 虚拟环境
if [ ! -f "$PYTHON_PATH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 未找到 Python: $PYTHON_PATH" >> "$LOG_FILE"
    exit 1
fi

# 切换到项目目录
cd "${PROJECT_ROOT}/src"

# 执行导出
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 执行导出命令..." >> "$LOG_FILE"

"$PYTHON_PATH" -m ominime.main obsidian >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 导出成功" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 导出失败，退出码: $EXIT_CODE" >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 导出完成" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE
