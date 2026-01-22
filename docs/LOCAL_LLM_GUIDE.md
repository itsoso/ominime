# 本地 LLM 部署完整指南

## 📖 目录

1. [为什么使用本地 LLM](#为什么使用本地-llm)
2. [方案对比](#方案对比)
3. [快速开始](#快速开始)
4. [方案 1: Ollama（推荐）](#方案-1-ollama推荐)
5. [方案 2: 本地 Qwen 模型](#方案-2-本地-qwen-模型)
6. [方案 3: 公司内部模型](#方案-3-公司内部模型)
7. [性能优化](#性能优化)
8. [故障排查](#故障排查)

---

## 为什么使用本地 LLM

### ✅ 优势

1. **隐私安全**
   - 所有数据在本地处理，不上传到云端
   - 适合处理敏感的工作内容
   - 符合公司数据安全政策

2. **成本优化**
   - 无 API 调用费用
   - 长期使用更经济
   - 不受 API 配额限制

3. **离线可用**
   - 无需网络连接
   - 不受 API 服务中断影响
   - 响应速度更稳定

4. **灵活定制**
   - 可以使用特定领域的模型
   - 可以微调模型以适应个人需求

### ⚠️ 注意事项

1. **硬件要求**
   - 需要较好的 CPU/GPU
   - 至少 16GB 内存（推荐 32GB）
   - ~20GB 磁盘空间

2. **首次设置**
   - 需要下载大模型文件（~14GB）
   - 首次加载较慢

3. **质量权衡**
   - 7B 模型质量接近 GPT-3.5
   - 不如 GPT-4 但足够日常使用

---

## 方案对比

| 特性 | Ollama | 本地 Qwen | OpenAI API | 公司模型 |
|------|--------|-----------|------------|----------|
| **隐私性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| **成本** | 免费 | 免费 | 按量付费 | 取决于公司 |
| **设置难度** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐ |
| **响应速度** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **质量** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **资源管理** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **离线使用** | ✅ | ✅ | ❌ | ❌ |
| **内存占用** | 中 | 高 | 低 | 低 |

**推荐选择**:
- 🥇 **个人用户（注重隐私）**: Ollama
- 🥈 **高级用户（需要定制）**: 本地 Qwen
- 🥉 **团队用户（注重质量）**: OpenAI API 或公司模型

---

## 快速开始

### 一键设置（推荐）

```bash
cd /Users/liqiuhua/work/ominime
./scripts/setup_local_llm.sh
```

这个脚本会引导你:
1. 选择 LLM 方案
2. 自动安装依赖
3. 下载模型
4. 配置 .env 文件

### 测试配置

```bash
python3 scripts/test_llm.py
```

这会测试:
- 后端初始化
- 连接可用性
- 对话功能
- 响应性能

---

## 方案 1: Ollama（推荐）

### 为什么选择 Ollama？

- ✅ 最简单的设置流程
- ✅ 优秀的资源管理
- ✅ 支持多个模型
- ✅ 活跃的社区支持
- ✅ 自动优化硬件使用

### 安装步骤

#### 1. 安装 Ollama

**macOS**:
```bash
brew install ollama
```

**或从官网下载**: https://ollama.ai

#### 2. 启动服务

```bash
ollama serve
```

建议设置为开机自启:
```bash
# macOS
brew services start ollama
```

#### 3. 下载模型

```bash
# 推荐: Qwen 2.5 7B（平衡性能和质量）
ollama pull qwen2.5:7b

# 或其他选项:
ollama pull qwen2.5:14b    # 更好的质量，需要更多内存
ollama pull qwen2.5:1.5b   # 更快，适合低配置
```

#### 4. 配置 OmniMe

编辑 `.env` 文件:

```bash
# AI 功能开关
AI_ENABLED=true

# Ollama 配置
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
```

#### 5. 测试

```bash
# 测试 Ollama
ollama run qwen2.5:7b "你好"

# 测试 OmniMe 集成
python3 scripts/test_llm.py
```

### Ollama 常用命令

```bash
# 列出已下载的模型
ollama list

# 删除模型
ollama rm qwen2.5:7b

# 查看模型信息
ollama show qwen2.5:7b

# 更新模型
ollama pull qwen2.5:7b
```

---

## 方案 2: 本地 Qwen 模型

### 为什么选择本地 Qwen？

- ✅ 完全控制模型
- ✅ 可以使用量化版本节省内存
- ✅ 支持模型微调
- ✅ 更灵活的配置

### 硬件要求

**最低配置**:
- CPU: 8 核
- RAM: 16GB
- 磁盘: 20GB

**推荐配置**:
- CPU: 16 核
- RAM: 32GB
- GPU: NVIDIA GPU（8GB+ VRAM）或 Apple M 系列
- 磁盘: 50GB SSD

### 安装步骤

#### 1. 安装 Python 依赖

```bash
cd /Users/liqiuhua/work/ominime
source venv/bin/activate
pip install transformers torch accelerate
```

**GPU 支持**:

```bash
# NVIDIA GPU (CUDA)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Apple Silicon (MPS)
# macOS 自带，无需额外安装
```

#### 2. 配置 OmniMe

编辑 `.env` 文件:

```bash
# AI 功能开关
AI_ENABLED=true

# 本地 Qwen 配置
LLM_BACKEND=qwen-local
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct
```

**模型选项**:

```bash
# 标准版本（推荐）
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct

# 量化版本（节省内存）
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4

# 更大的模型（需要更多资源）
QWEN_MODEL=Qwen/Qwen2.5-14B-Instruct
```

#### 3. 首次运行

```bash
# 首次运行会自动下载模型（~14GB）
python3 scripts/test_llm.py
```

模型会下载到: `~/.cache/huggingface/hub/`

### 性能优化

#### GPU 加速

**NVIDIA GPU**:
```bash
# 检查 CUDA 是否可用
python3 -c "import torch; print(torch.cuda.is_available())"
```

**Apple Silicon**:
```bash
# 检查 MPS 是否可用
python3 -c "import torch; print(torch.backends.mps.is_available())"
```

#### 内存优化

如果内存不足，使用量化模型:

```bash
# 4-bit 量化（内存占用 ~4GB）
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4

# 8-bit 量化（内存占用 ~7GB）
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct-GPTQ-Int8
```

---

## 方案 3: 公司内部模型

### 适用场景

- 公司部署了兼容 OpenAI API 的大模型
- 需要使用公司的专有模型
- 公司有数据安全要求

### 配置步骤

#### 1. 获取公司 API 信息

需要从公司获取:
- API 地址（Base URL）
- API Key
- 模型名称

#### 2. 配置 OmniMe

编辑 `.env` 文件:

```bash
# AI 功能开关
AI_ENABLED=true

# 公司模型配置
LLM_BACKEND=openai
OPENAI_API_KEY=your-company-api-key
OPENAI_BASE_URL=https://your-company-llm-api.com/v1
OPENAI_MODEL=your-company-model-name
```

#### 3. 测试连接

```bash
python3 scripts/test_llm.py
```

### 常见公司部署方案

**Azure OpenAI**:
```bash
OPENAI_BASE_URL=https://your-resource.openai.azure.com/
OPENAI_API_KEY=your-azure-key
OPENAI_MODEL=gpt-4
```

**自建 vLLM 服务**:
```bash
OPENAI_BASE_URL=http://your-company-server:8000/v1
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=qwen2.5-7b
```

---

## 性能优化

### Ollama 优化

#### 1. 调整并发数

```bash
# 设置最大并发请求数
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=4
```

#### 2. 使用 GPU

Ollama 会自动检测并使用 GPU，无需额外配置。

#### 3. 模型预加载

```bash
# 预加载模型到内存
ollama run qwen2.5:7b ""
```

### 本地 Qwen 优化

#### 1. 使用 Flash Attention

```bash
pip install flash-attn
```

#### 2. 批处理优化

在代码中使用批处理可以提高吞吐量（已在 `llm_backend.py` 中实现）。

#### 3. 模型量化

使用 GPTQ 或 AWQ 量化可以显著降低内存占用和提高速度。

---

## 故障排查

### Ollama 问题

#### 问题: 连接失败

```bash
# 检查服务是否运行
ps aux | grep ollama

# 重启服务
killall ollama
ollama serve
```

#### 问题: 模型下载失败

```bash
# 使用镜像（国内用户）
export OLLAMA_MODELS=/path/to/models
ollama pull qwen2.5:7b
```

#### 问题: 响应太慢

```bash
# 使用更小的模型
ollama pull qwen2.5:1.5b

# 或调整参数
ollama run qwen2.5:7b --num-gpu 1
```

### 本地 Qwen 问题

#### 问题: 内存不足

```python
# 使用量化模型
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4
```

#### 问题: 模型下载慢

```bash
# 使用国内镜像
export HF_ENDPOINT=https://hf-mirror.com
```

#### 问题: GPU 未被使用

```bash
# 检查 CUDA
python3 -c "import torch; print(torch.cuda.is_available())"

# 检查 MPS (Mac)
python3 -c "import torch; print(torch.backends.mps.is_available())"
```

### 通用问题

#### 问题: AI 功能不可用

1. 检查 `.env` 配置:
```bash
cat .env | grep -E "AI_ENABLED|LLM_BACKEND"
```

2. 测试后端:
```bash
python3 scripts/test_llm.py
```

3. 查看日志:
```bash
tail -f ~/Library/Logs/ominime/app.log
```

#### 问题: 响应质量差

1. 调整温度参数（在代码中）
2. 尝试更大的模型
3. 增加 max_tokens

---

## 最佳实践

### 1. 混合使用

```bash
# 日常使用本地模型
LLM_BACKEND=ollama

# 重要分析使用 OpenAI
# 临时切换: 修改 .env 后重启服务
```

### 2. 定期更新模型

```bash
# Ollama
ollama pull qwen2.5:7b

# 本地 Qwen
rm -rf ~/.cache/huggingface/hub/models--Qwen--*
# 重新运行会自动下载最新版本
```

### 3. 监控资源使用

```bash
# 查看内存使用
top -o MEM

# 查看 GPU 使用 (NVIDIA)
nvidia-smi

# 查看 GPU 使用 (Mac)
sudo powermetrics --samplers gpu_power -i 1000
```

---

## 总结

| 如果你... | 推荐方案 |
|----------|----------|
| 想要最简单的设置 | Ollama |
| 注重隐私和离线使用 | Ollama 或本地 Qwen |
| 需要最佳质量 | OpenAI API |
| 有公司部署的模型 | 公司内部模型 |
| 想要完全控制 | 本地 Qwen |
| 内存有限（<16GB） | Ollama + 小模型 |
| 有强大 GPU | 本地 Qwen |

**快速开始**:
```bash
./scripts/setup_local_llm.sh
python3 scripts/test_llm.py
```

祝你使用愉快！🎉
