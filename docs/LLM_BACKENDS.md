# LLM 后端配置指南

OmniMe 支持多种大模型后端，你可以根据需求选择：

## 支持的后端

### 1. OpenAI API（默认）

**适用场景**：
- 需要最佳的分析质量
- 有网络连接
- 可以接受 API 费用

**配置**：
```bash
# .env 文件
LLM_BACKEND=openai
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o-mini  # 可选，默认 gpt-4o-mini
```

---

### 2. 本地 Qwen 模型（推荐隐私保护）

**适用场景**：
- 注重隐私安全
- 有较好的硬件（16GB+ RAM）
- 不想依赖网络

**硬件要求**：
- CPU: 至少 8 核
- RAM: 16GB+（推荐 32GB）
- GPU: 可选，有 NVIDIA GPU 会更快
- 磁盘: ~20GB 空间

**安装步骤**：

1. 安装依赖：
```bash
pip install transformers torch accelerate
```

2. 配置 .env：
```bash
LLM_BACKEND=qwen-local
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct  # 可选，默认此模型
```

3. 首次运行会自动下载模型（~14GB）

**性能优化**：
- **有 NVIDIA GPU**：自动使用 CUDA 加速
- **Mac M 系列芯片**：自动使用 MPS 加速
- **仅 CPU**：较慢但可用

---

### 3. Ollama 本地服务（最简单）

**适用场景**：
- 想要本地部署但不想管理 Python 依赖
- 需要同时运行多个模型
- 想要更好的资源管理

**安装步骤**：

1. 安装 Ollama：
```bash
# macOS
brew install ollama

# 或从官网下载: https://ollama.ai
```

2. 启动 Ollama 服务：
```bash
ollama serve
```

3. 下载 Qwen 模型：
```bash
ollama pull qwen2.5:7b
```

4. 配置 .env：
```bash
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434  # 可选，默认此地址
```

---

### 4. 公司内部大模型

**适用场景**：
- 公司部署了兼容 OpenAI API 的大模型服务
- 需要使用公司的模型

**配置**：
```bash
LLM_BACKEND=openai
OPENAI_API_KEY=your-company-api-key
OPENAI_BASE_URL=https://your-company-llm-api.com/v1  # 公司 API 地址
OPENAI_MODEL=your-company-model-name
```

---

## 配置示例

### 完整 .env 示例（OpenAI）
```bash
# AI 功能开关
AI_ENABLED=true

# LLM 后端配置
LLM_BACKEND=openai
OPENAI_API_KEY=sk-proj-xxx
OPENAI_MODEL=gpt-4o-mini
```

### 完整 .env 示例（本地 Qwen）
```bash
# AI 功能开关
AI_ENABLED=true

# LLM 后端配置
LLM_BACKEND=qwen-local
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct
```

### 完整 .env 示例（Ollama）
```bash
# AI 功能开关
AI_ENABLED=true

# LLM 后端配置
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
```

---

## 性能对比

| 后端 | 速度 | 质量 | 隐私 | 成本 | 硬件要求 |
|------|------|------|------|------|----------|
| OpenAI API | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | 💰💰 | 低 |
| Qwen Local | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 免费 | 高 |
| Ollama | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 免费 | 中 |

---

## 推荐配置

### 个人用户（注重隐私）
→ **Ollama** 或 **Qwen Local**

### 团队用户（注重质量）
→ **OpenAI API** 或 **公司内部模型**

### 开发测试
→ **OpenAI API**（快速迭代）

---

## 故障排查

### Qwen Local 内存不足
```bash
# 使用量化版本（需要更少内存）
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4
```

### Ollama 连接失败
```bash
# 检查服务是否运行
ollama list

# 重启服务
ollama serve
```

### OpenAI API 超时
```bash
# 检查代理设置
unset http_proxy https_proxy

# 或使用国内中转
OPENAI_BASE_URL=https://your-proxy.com/v1
```

---

## 切换后端

只需修改 `.env` 文件中的 `LLM_BACKEND` 配置，无需修改代码：

```bash
# 切换到本地 Qwen
LLM_BACKEND=qwen-local

# 切换回 OpenAI
LLM_BACKEND=openai
```

重启服务后生效。
