# 本地 LLM 后端配置

OmniMe 的 AI 分析只允许在本机运行。支持以下两种后端：

| 后端 | 推荐场景 | 数据边界 |
| --- | --- | --- |
| Ollama | 默认推荐，安装和模型管理简单 | 请求仅发送到 `127.0.0.1:11434` |
| 本地 Qwen | 需要直接使用 Transformers | 模型在 OmniMe 进程内运行 |

OpenAI、兼容 OpenAI 的公司接口和阿里云 TokenPlan 都是远程服务，当前版本不接入，也不会读取 `OPENAI_API_KEY`。

## Ollama（推荐）

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b
```

`.env`：

```bash
AI_ENABLED=true
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

## 进程内 Qwen

先在项目虚拟环境安装可选依赖：

```bash
venv/bin/pip install transformers torch accelerate
```

`.env`：

```bash
AI_ENABLED=true
LLM_BACKEND=qwen-local
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct
```

首次使用需要下载模型文件；分析内容本身不会发送到模型托管站点。

## 检查与切换

```bash
venv/bin/python scripts/check_llm.py
```

切换后重启 OmniMe。后端不可用或推理失败时，日报会明确降级到基础统计摘要，不会静默调用其他服务。
