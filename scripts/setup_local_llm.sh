#!/bin/bash

# 本地 LLM 设置脚本
# 帮助用户快速配置本地 Qwen 模型或 Ollama 服务

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 OmniMe 本地 LLM 设置向导"
echo "================================"
echo ""

# 检查虚拟环境
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo "❌ 未找到虚拟环境，请先运行: python3 -m venv venv"
    exit 1
fi

echo "请选择要使用的本地 LLM 方案:"
echo ""
echo "1) Ollama (推荐 - 最简单，资源管理好)"
echo "2) 本地 Qwen 模型 (需要更多内存，但更灵活)"
echo "3) 保持使用 OpenAI API"
echo ""
read -p "请输入选项 (1-3): " choice

case $choice in
    1)
        echo ""
        echo "📦 设置 Ollama..."
        echo ""
        
        # 检查是否安装了 Ollama
        if ! command -v ollama &> /dev/null; then
            echo "Ollama 未安装。"
            echo ""
            echo "安装方法:"
            echo "  macOS: brew install ollama"
            echo "  或访问: https://ollama.ai"
            echo ""
            read -p "是否现在安装 Ollama? (y/n): " install_ollama
            
            if [ "$install_ollama" = "y" ]; then
                if command -v brew &> /dev/null; then
                    brew install ollama
                else
                    echo "❌ 未找到 Homebrew，请手动安装 Ollama"
                    exit 1
                fi
            else
                echo "请手动安装 Ollama 后重新运行此脚本"
                exit 1
            fi
        fi
        
        echo "✅ Ollama 已安装"
        echo ""
        
        # 启动 Ollama 服务
        echo "启动 Ollama 服务..."
        if ! pgrep -x "ollama" > /dev/null; then
            ollama serve &
            sleep 3
        fi
        
        # 下载模型
        echo ""
        echo "可用的 Qwen 模型:"
        echo "  1) qwen2.5:7b (推荐 - 平衡性能和质量)"
        echo "  2) qwen2.5:14b (更好的质量，需要更多内存)"
        echo "  3) qwen2.5:1.5b (最快，适合低配置)"
        echo ""
        read -p "选择模型 (1-3, 默认 1): " model_choice
        
        case ${model_choice:-1} in
            1) MODEL="qwen2.5:7b" ;;
            2) MODEL="qwen2.5:14b" ;;
            3) MODEL="qwen2.5:1.5b" ;;
            *) MODEL="qwen2.5:7b" ;;
        esac
        
        echo ""
        echo "下载模型 $MODEL (这可能需要几分钟)..."
        ollama pull $MODEL
        
        echo ""
        echo "✅ Ollama 设置完成！"
        echo ""
        echo "配置信息:"
        echo "  LLM_BACKEND=ollama"
        echo "  OLLAMA_MODEL=$MODEL"
        echo "  OLLAMA_BASE_URL=http://localhost:11434"
        echo ""
        
        # 更新 .env 文件
        if [ -f "$PROJECT_ROOT/.env" ]; then
            # 备份
            cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.backup"
            
            # 更新配置
            sed -i '' '/^LLM_BACKEND=/d' "$PROJECT_ROOT/.env"
            sed -i '' '/^OLLAMA_MODEL=/d' "$PROJECT_ROOT/.env"
            sed -i '' '/^OLLAMA_BASE_URL=/d' "$PROJECT_ROOT/.env"
            
            echo "" >> "$PROJECT_ROOT/.env"
            echo "# Ollama 配置" >> "$PROJECT_ROOT/.env"
            echo "LLM_BACKEND=ollama" >> "$PROJECT_ROOT/.env"
            echo "OLLAMA_MODEL=$MODEL" >> "$PROJECT_ROOT/.env"
            echo "OLLAMA_BASE_URL=http://localhost:11434" >> "$PROJECT_ROOT/.env"
            
            echo "✅ .env 文件已更新"
        else
            echo "⚠️  未找到 .env 文件，请手动添加配置"
        fi
        ;;
        
    2)
        echo ""
        echo "📦 设置本地 Qwen 模型..."
        echo ""
        
        # 检查硬件
        TOTAL_MEM=$(sysctl hw.memsize | awk '{print int($2/1024/1024/1024)}')
        echo "检测到系统内存: ${TOTAL_MEM}GB"
        
        if [ $TOTAL_MEM -lt 16 ]; then
            echo "⚠️  警告: 建议至少 16GB 内存运行 Qwen-7B"
            read -p "是否继续? (y/n): " continue_setup
            if [ "$continue_setup" != "y" ]; then
                exit 1
            fi
        fi
        
        # 安装依赖
        echo ""
        echo "安装 Python 依赖..."
        source "$PROJECT_ROOT/venv/bin/activate"
        pip install transformers torch accelerate -q
        
        echo ""
        echo "✅ 依赖安装完成"
        echo ""
        echo "可用的模型:"
        echo "  1) Qwen/Qwen2.5-7B-Instruct (推荐)"
        echo "  2) Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4 (量化版本，内存占用更小)"
        echo ""
        read -p "选择模型 (1-2, 默认 1): " model_choice
        
        case ${model_choice:-1} in
            1) MODEL="Qwen/Qwen2.5-7B-Instruct" ;;
            2) MODEL="Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4" ;;
            *) MODEL="Qwen/Qwen2.5-7B-Instruct" ;;
        esac
        
        echo ""
        echo "✅ 本地 Qwen 设置完成！"
        echo ""
        echo "配置信息:"
        echo "  LLM_BACKEND=qwen-local"
        echo "  QWEN_MODEL=$MODEL"
        echo ""
        echo "⚠️  注意: 首次运行时会自动下载模型 (~14GB)，请耐心等待"
        echo ""
        
        # 更新 .env 文件
        if [ -f "$PROJECT_ROOT/.env" ]; then
            # 备份
            cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.backup"
            
            # 更新配置
            sed -i '' '/^LLM_BACKEND=/d' "$PROJECT_ROOT/.env"
            sed -i '' '/^QWEN_MODEL=/d' "$PROJECT_ROOT/.env"
            
            echo "" >> "$PROJECT_ROOT/.env"
            echo "# 本地 Qwen 配置" >> "$PROJECT_ROOT/.env"
            echo "LLM_BACKEND=qwen-local" >> "$PROJECT_ROOT/.env"
            echo "QWEN_MODEL=$MODEL" >> "$PROJECT_ROOT/.env"
            
            echo "✅ .env 文件已更新"
        else
            echo "⚠️  未找到 .env 文件，请手动添加配置"
        fi
        ;;
        
    3)
        echo ""
        echo "📦 保持使用 OpenAI API"
        echo ""
        echo "请确保 .env 文件中配置了:"
        echo "  LLM_BACKEND=openai"
        echo "  OPENAI_API_KEY=sk-xxx"
        echo ""
        ;;
        
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac

echo ""
echo "🎉 设置完成！"
echo ""
echo "下一步:"
echo "  1. 重启 OmniMe 服务: ./scripts/install_all.sh"
echo "  2. 测试 AI 功能: python3 -m ominime.main report --ai"
echo ""
