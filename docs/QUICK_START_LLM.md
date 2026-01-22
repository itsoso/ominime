# 🚀 本地 LLM 快速开始

## 一分钟快速设置

### 方案 1: Ollama（最推荐）

```bash
# 1. 安装 Ollama
brew install ollama

# 2. 启动服务（新终端窗口）
ollama serve

# 3. 下载模型
ollama pull qwen2.5:7b

# 4. 配置 OmniMe
cat >> /Users/liqiuhua/work/ominime/.env << EOF
AI_ENABLED=true
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
EOF

# 5. 测试
cd /Users/liqiuhua/work/ominime
python3 scripts/test_llm.py

# 6. 重启服务
./scripts/install_all.sh
```

**完成！** 现在你的数据完全本地化，不会上传到任何云端。

---

### 方案 2: 自动设置向导

```bash
cd /Users/liqiuhua/work/ominime
./scripts/setup_local_llm.sh
```

按提示选择方案即可。

---

## 验证是否工作

### 1. 测试后端

```bash
python3 scripts/test_llm.py
```

应该看到：
```
✅ 后端初始化成功
✅ 后端可用
✅ 对话测试成功
```

### 2. 生成报告

```bash
cd /Users/liqiuhua/work/ominime
source venv/bin/activate
python3 -m ominime.main report --ai
```

应该看到包含 AI 分析的报告。

### 3. 检查每日导出

```bash
# 手动触发导出
./scripts/daily_export.sh

# 检查 Obsidian 目录
ls -lh /Users/liqiuhua/work/personal/obsidian/personal/OmniMe-*.md
```

---

## 常见问题

### Q: Ollama 连接失败？

```bash
# 检查服务是否运行
ps aux | grep ollama

# 如果没有运行，启动它
ollama serve
```

### Q: 模型下载慢？

国内用户可以使用镜像：
```bash
export OLLAMA_MODELS=/path/to/models
ollama pull qwen2.5:7b
```

### Q: 内存不够？

使用更小的模型：
```bash
ollama pull qwen2.5:1.5b
# 然后修改 .env: OLLAMA_MODEL=qwen2.5:1.5b
```

### Q: 想切换回 OpenAI？

编辑 `.env`:
```bash
LLM_BACKEND=openai
OPENAI_API_KEY=sk-xxx
```

重启服务即可。

---

## 性能对比

| 模型 | 内存占用 | 速度 | 质量 | 适用场景 |
|------|----------|------|------|----------|
| qwen2.5:1.5b | ~2GB | 很快 | 一般 | 低配置机器 |
| qwen2.5:7b | ~5GB | 快 | 好 | 日常使用（推荐） |
| qwen2.5:14b | ~10GB | 中等 | 很好 | 高质量分析 |
| GPT-4o-mini | 无 | 很快 | 最好 | 云端 API |

---

## 下一步

- 📖 查看完整文档: [LOCAL_LLM_GUIDE.md](LOCAL_LLM_GUIDE.md)
- 🔧 后端配置对比: [LLM_BACKENDS.md](LLM_BACKENDS.md)
- 🎯 优化性能: 查看文档中的"性能优化"章节

---

**享受完全本地化的 AI 分析！** 🎉
