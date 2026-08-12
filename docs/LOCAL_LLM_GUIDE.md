# 本地 LLM 部署指南

OmniMe 只支持本地 AI。最省心的方案是 Ollama；内存充足且需要直接控制 Transformers 时，可以选择进程内 Qwen。

## 自动设置

```bash
./scripts/setup_local_llm.sh
```

向导只会提供 Ollama 和本地 Qwen，不会要求或保存远程 API Key。

## Ollama

```bash
brew install ollama
ollama serve
ollama pull qwen2.5:7b
```

推荐配置：

```bash
AI_ENABLED=true
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

常用模型：

- `qwen2.5:1.5b`：内存占用较小。
- `qwen2.5:7b`：默认推荐。
- `qwen2.5:14b`：质量更高，但需要更多内存。

## 进程内 Qwen

```bash
venv/bin/pip install transformers torch accelerate
```

配置：

```bash
AI_ENABLED=true
LLM_BACKEND=qwen-local
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct
```

首次运行会下载模型文件，可能耗时较长并占用大量磁盘和内存。Apple Silicon 会优先使用 MPS；不可用时回退 CPU。

## 验证

```bash
venv/bin/python scripts/check_llm.py
```

成功后重启：

```bash
./scripts/install_all.sh
```

如果检查失败：

1. 确认 `.env` 中 `AI_ENABLED=true`。
2. Ollama 用户运行 `ollama list` 并确认服务监听 `127.0.0.1:11434`。
3. Qwen 用户确认虚拟环境内已安装 `transformers`、`torch` 和 `accelerate`。
4. 查看 `~/.ominime/logs/` 下的运行日志。

AI 不可用时，OmniMe 会返回基础统计摘要；输入捕获、统计和导出不受影响。

## 为什么不接 TokenPlan

阿里云百炼 TokenPlan 提供的是远程模型调用。即使模型属于 Qwen 系列，输入内容仍需要离开本机，因此与当前“只走本地”的隐私边界冲突。若未来确实需要接入，应作为独立、明确同意的产品模式设计，而不是复用本地开关或静默降级。
