# 本地 AI 快速开始

推荐使用 Ollama：

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b
```

在项目根目录创建或更新 `.env`：

```bash
AI_ENABLED=true
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

检查后端并重启服务：

```bash
venv/bin/python scripts/check_llm.py
./scripts/install_app.sh
```

OmniMe 不使用 OpenAI Key，不支持远程分析。关闭 AI 时，基础统计和导出仍然可用。

更多选项见 [本地 LLM 后端配置](LLM_BACKENDS.md)。
