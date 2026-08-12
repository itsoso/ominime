# OmniMe Security and Capture Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 封住本地输入数据暴露与跨应用误归属，移除伪多模态分析和 EventTap 截图风险，并统一隐私、统计、依赖与部署语义。

**Architecture:** 保留现有 Enter snapshot 持久化主链路，把原生 callback 收缩为事件采样；worker 只读取目标 PID 的最小 AX 信息。Web 采用 loopback/同源边界，AI 只使用 loopback Ollama 或进程内 Qwen；历史数据库列保留兼容，但运行时不再产生 Qwen-VL 数据。

**Tech Stack:** Python 3.10+、PyObjC、FastAPI、SQLite、rumps、pytest、原生 HTML/JavaScript。

---

### Task 1: Web 同源边界、路由和 XSS

**Files:**
- Modify: `src/ominime/web/api.py`
- Modify: `src/ominime/web/templates/index.html`
- Modify: `tests/test_web_health.py`
- Modify: `tests/test_dashboard_template.py`
- Create: `tests/test_web_security.py`

**Step 1: Write failing tests**

- 使用 TestClient 验证 `Origin: https://evil.example` 得到 403。
- 验证 loopback/测试 Host 的同源请求仍为 200。
- 验证 `/api/report/full` 不再进入日期动态路由。
- 模板测试要求 `display_name`、`work_pattern`、`p.app` 经 `escapeHtml`，并要求页面不再加载 Google Fonts。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_web_security.py tests/test_web_health.py tests/test_dashboard_template.py -q`

Expected: 恶意 Origin、静态路由和模板转义断言失败。

**Step 3: Implement minimal boundary**

- 删除通配 `CORSMiddleware`。
- 增加只允许 loopback/test client Host 和同源/无 Origin 请求的 HTTP middleware；预检跨域请求返回 403。
- 将 `/api/report/full` 注册到动态日期路由之前。
- 所有服务端/配置来源的字符串在进入 `innerHTML` 前调用 `escapeHtml`。
- 移除 Google Fonts；保留系统字体栈。

**Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_web_security.py tests/test_web_health.py tests/test_dashboard_template.py -q`

Expected: PASS。

### Task 2: 目标 PID 优先的 AX 捕获

**Files:**
- Modify: `src/ominime/context_capture.py`
- Modify: `tests/test_context_capture.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write failing tests**

- `target_pid` 存在时先调用 `get_focused_element(target_pid)`，不使用另一个系统焦点。
- 目标 PID 查询失败时返回 degraded，不跨进程接受系统焦点。
- 快速切 app 的 Enter snapshot 不保存新前台 app 的文本。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_context_capture.py tests/test_keyboard_listener_capture.py -q`

Expected: PID 优先断言失败。

**Step 3: Implement minimal fix**

在 `capture_accessibility_context()` 中，有有效 `target_pid` 时只查询该应用的焦点元素；仅无 PID 的调用才使用 system-wide 查询。保持现有 secure/text-role 规则。

**Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_context_capture.py tests/test_keyboard_listener_capture.py -q`

Expected: PASS。

### Task 3: 从 EventTap 默认路径移除整窗 OCR

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `src/ominime/config.py`
- Modify: `tests/test_keyboard_listener_capture.py`
- Modify: `tests/test_config.py`

**Step 1: Write failing tests**

- 默认配置下 Kim/微信 Enter callback 不调用 `composer_capture.freeze()`。
- ignored app、secure/count-only 模式都不触发预提交截图。
- EventTap callback 仍正确入队 Enter 身份和时间。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_config.py -q`

Expected: 当前默认调用截图，测试失败。

**Step 3: Implement minimal fix**

删除 EventTap callback 中同步 `freeze()`；不再给 RawKeyboardEvent 附带整窗像素。移除因此失去生产调用的 composer 映射和预提交 OCR 分支，保留可信 AXValue 与 count-only fallback。

**Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_config.py -q`

Expected: PASS，且 listener 不再引用 `freeze()`。

### Task 4: 删除 Qwen-VL submission 分析

**Files:**
- Delete: `src/ominime/multimodal_backend.py`
- Delete: `tests/test_multimodal_backend.py`
- Delete: `requirements-qwen-vl.txt`
- Modify: `src/ominime/submission_processor.py`
- Modify: `src/ominime/config.py`
- Modify: `src/ominime/web/api.py`
- Modify: `src/ominime/web/templates/index.html`
- Modify: `tests/test_submission_processor.py`
- Modify: `tests/test_web_health.py`

**Step 1: Write failing tests**

- 保存提交不会创建线程或调用 backend。
- health/submissions API 不再暴露 multimodal/Qwen 字段。
- 配置保存不再写 Qwen 字段。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_submission_processor.py tests/test_web_health.py tests/test_dashboard_template.py -q`

Expected: 旧字段/线程仍存在导致失败。

**Step 3: Remove runtime feature**

- `save_submission_event` 始终同步保存，analysis status 仅用于旧表兼容并写 disabled。
- 删除分析线程和 backend 模块。
- 删除配置、health、API 和 UI 的 Qwen/多模态字段。
- 保留 SQLite 旧列，避免破坏历史数据库。
- 删除只服务于截图分析且无生产调用的 `ScreenshotScope`。

**Step 4: Verify no references and GREEN**

Run: `rg -n "qwen|multimodal|ScreenshotScope|choose_screenshot_scope" src tests requirements*`

Expected: 无运行时引用；仅历史迁移注释如有需要可保留。

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_submission_processor.py tests/test_context_capture.py tests/test_web_health.py tests/test_dashboard_template.py -q`

Expected: PASS。

### Task 5: 本地 AI 边界和可靠回退

**Files:**
- Modify: `src/ominime/config.py`
- Modify: `src/ominime/analyzer.py`
- Modify: `src/ominime/llm_backend.py`
- Modify: `src/ominime/web/templates/index.html`
- Modify: `src/ominime/menu_bar_app.py`
- Modify: `tests/test_analyzer_llm.py`
- Modify: `tests/test_config.py`

**Step 1: Write failing tests**

- 配置、后端工厂和安装元数据中不再存在 OpenAI Key/后端。
- backend.chat 抛错时规则总结只执行一次且正常返回。
- Ollama POST 使用有限 timeout。
- UI/关于文本准确说明 AI 仅使用本地模型。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_analyzer_llm.py tests/test_config.py -q`

Expected: 自动开启和递归回退测试失败。

**Step 3: Implement minimal fix**

- 删除 OpenAI 配置、后端类、可选依赖和文档入口。
- 默认使用 Ollama，并拒绝非 loopback 的 Ollama 地址。
- 提取纯规则 `_generate_basic_summary()`，AI 失败直接调用它。
- 为 Ollama chat 设置明确 timeout。
- 修改本地存储声明，明确本地 AI 边界。

**Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_analyzer_llm.py tests/test_config.py -q`

Expected: PASS。

### Task 6: 修正统计语义和数据库并发基础

**Files:**
- Modify: `src/ominime/database.py`
- Modify: `src/ominime/web/templates/index.html`
- Modify: `tests/test_database.py`
- Modify: `tests/test_web_api.py`

**Step 1: Write failing tests**

- 单条 duration=0 的提交不能被统计成一分钟。
- 按 `app_bundle_id` 分组时样本和时长也使用 bundle id。
- 连接启用 foreign_keys、busy_timeout；初始化数据库启用 WAL。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_database.py tests/test_web_api.py -q`

Expected: 人为加一分钟和连接 PRAGMA 断言失败。

**Step 3: Implement minimal fix**

- 使用记录的 `duration_seconds`，不再给每个 session 加一分钟。
- 查询全程使用 bundle id，并消除任意 app_name/display_name 选择。
- 连接设置 `foreign_keys=ON`、`busy_timeout`；初始化设置 WAL。
- 页面把无可靠时长显示为“暂无可靠时长”，不再据此宣称效率。

**Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_database.py tests/test_web_api.py -q`

Expected: PASS。

### Task 7: 文件权限、依赖和唯一部署入口

**Files:**
- Modify: `src/ominime/config.py`
- Modify: `src/ominime/database.py`
- Modify: `setup.py`
- Create: `pyproject.toml`
- Create: `pytest.ini`
- Rename: `scripts/test_llm.py` to `scripts/check_llm.py`
- Modify: `scripts/install_app.sh`
- Modify: `src/ominime/scripts/status_all.sh`
- Modify: `src/ominime/scripts/web_status.sh`
- Modify: `tests/test_install_scripts_arch.py`
- Create: `tests/test_file_permissions.py`

**Step 1: Write failing tests**

- 新建 data dir 为 0700，DB/config/runtime state 为 0600。
- pytest 只收集 `tests/`。
- 安装脚本 load LaunchAgent 后不再执行第二个 `ominime app &`。
- 状态脚本请求存在的 `/api/health`。
- 安装元数据包含 Web 运行依赖。

**Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_file_permissions.py tests/test_install_scripts_arch.py -q`

Expected: 权限、双启动、旧 health 路由断言失败。

**Step 3: Implement minimal fix**

- 创建/加载时收紧敏感路径权限，不递归修改用户导出目录。
- 增加 build-system 和 pytest 配置；让 setup runtime 依赖与实际入口一致。
- 真实 LLM 脚本改名、使用退出码且不打印 Key。
- 安装脚本只由 LaunchAgent 启动，状态检查统一 `/api/health`。

**Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_file_permissions.py tests/test_install_scripts_arch.py -q`

Expected: PASS。

Run: `venv/bin/python -m pip check`

Expected: No broken requirements found。

### Task 8: 删除本轮确认的孤儿实现并增强可观测性

**Files:**
- Delete: `src/ominime/input_diff.py`
- Delete: `tests/test_input_diff.py`
- Modify: `src/ominime/menu_bar_app.py`
- Modify: `src/ominime/main.py`
- Delete: `src/ominime/menu_bar.py`
- Modify: `src/ominime/keyboard_listener.py`
- Modify: relevant tests

**Step 1: Write/adjust behavior tests**

- `ominime start` 与 `ominime app` 进入同一实现。
- worker 异常会写入 runtime diagnostics，而不是仅 debug print。
- menu app 不再构造没有输入调用者的 AppTracker。

**Step 2: Verify RED**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_menu_bar_daily_counter.py tests/test_keyboard_listener_capture.py -q`

Expected: legacy/tracker/diagnostics 断言失败。

**Step 3: Remove orphans and expose errors**

- `cmd_start` 转发唯一的 `menu_bar_app.run_app`，删除 legacy menu。
- 删除无生产引用的 input_diff 和 AppTracker menu wiring；若 `app_tracker.py` 无剩余生产入口则一并删除。
- worker 异常写入 runtime state 的 last error/counter。

**Step 4: Run focused tests**

Run: `PYTHONPATH=src venv/bin/python -m pytest tests/test_menu_bar_daily_counter.py tests/test_keyboard_listener_capture.py -q`

Expected: PASS。

### Task 9: 全量验证、提交和本地运行检查

**Files:**
- Modify: `README.md` if user-facing behavior changed
- Modify: relevant docs/tests only as required

**Step 1: Static verification**

Run: `PYTHONPATH=src venv/bin/python -m compileall -q src tests`

Expected: exit 0。

Run: `bash -n scripts/*.sh src/ominime/scripts/*.sh`

Expected: exit 0。

**Step 2: Full tests**

Run: `PYTHONPATH=src venv/bin/python -m pytest -q`

Expected: 全部通过且不再收集 `scripts/check_llm.py`。

**Step 3: API smoke tests**

- 启动隔离端口服务。
- 验证 `/api/health`、`/api/report/full` 正常。
- 验证 evil Origin 和非 loopback Host 被拒绝。

**Step 4: Git scope audit**

Run: `git status --short && git diff --check && git diff --stat origin/main...HEAD`

Expected: 只包含本计划文件；用户原有未跟踪文件未被暂存或修改。

**Step 5: Commit in coherent slices**

仅用显式路径暂存每一阶段，禁止 `git add -A`。部署前回到干净、已验证的主干集成状态。
