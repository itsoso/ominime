# Kim/微信正文采集停滞恢复设计

## 目标

恢复 Kim 和微信长时间空闲后、长文本或视觉换行文本的本机正文采集，同时继续保证 Enter 不会被无限吞掉、EventTap 回调不执行原生截图、截图不落盘也不离开本机。

## 已验证根因

- OmniMe 进程、心跳、8001 Web 服务和 EventTap 均持续运行；停止的是正文保存，而不是服务进程。
- 2026-08-15 的运行诊断持续收到 Kim、微信和 ChatGPT 的 Enter，但 AX 返回 `focused element unavailable`，Kim/微信 OCR 随后返回空或多行不可信。
- 同一 Python 运行时中，Kim 长时间空闲后的首次目标 PID AX 查询实测约 377ms，超过当前 200ms Enter fail-open watchdog。watchdog 先重放 Enter 后，聊天输入框被清空，worker 再截图只能得到空框。
- 微信当前草稿可被 Vision 识别为两条有序视觉行，但现有 `multiline_untrusted` 规则无条件拒绝，因此较长或自动换行的正文无法保存。
- 辅助功能权限仍有效，Kim/微信窗口可枚举，worker 没有积压或卡死，也没有新的 Python 崩溃报告。

## 方案比较

### 方案 A：延长有界 watchdog，并接受可信多行 OCR（采用）

将 Enter fail-open 上限从 200ms 调整为 750ms。worker 仍先完成 AX 安全检查和内存帧冻结，随后立即成对重放 Enter keyDown/keyUp；Vision OCR 在重放后执行，不增加发送等待。对 Vision 返回的多条视觉行不再无条件拒绝，而是继续通过既有输入法、边缘、长度和物理按键数校验。

正常热路径会在 AX 和截图完成后立刻重放，不固定等待 750ms。750ms 只限制冷 AX、原生阻塞或 worker 异常时的最长吞键时间。

### 方案 B：持续预热 AX 和窗口状态

在普通输入期间周期性读取 AX 并缓存安全状态。它能缩短 Enter 路径，但引入缓存新鲜度、应用切换和并发失效问题，也增加持续后台读取，暂不采用。

### 方案 C：跳过 AX，先截图再检查

它能最快冻结输入内容，但可能在安全字段或非聊天界面复制窗口图像，违反既有隐私边界，不采用。

## 数据流

1. EventTap 回调只验证 Kim/微信的普通 Enter，复制并标记 keyDown/keyUp，成功入队后抑制原物理事件并启动 750ms watchdog。
2. worker 读取目标 PID 的 AX 上下文；secure 输入不截图。
3. 非 secure 输入冻结已预备的目标窗口帧，随后立即调用幂等重放路径；不等待 Vision OCR。
4. OCR 仅处理固定 composer ROI。单行和多视觉行都按顺序组装，再执行边缘裁切、输入法状态、最大长度和物理按键数校验。
5. 校验成功才保存正文；失败继续保存安全计数或跳过，并写入不含 UI 上下文内容的诊断。

## 安全与错误处理

- EventTap 回调继续禁止 AX、窗口枚举、截图和 Vision 调用。
- ignored、count-only、修饰键 Enter 和 autorepeat 不进入截图路径。
- watchdog、worker 正常路径和 worker `finally` 继续共享同一锁和 released 标记，只能重放一组 Enter。
- 750ms 到期后优先保证消息发送；此后产生的空帧或不可信 OCR 不保存正文。
- 图像仅存在内存，不写入文件、数据库、日志或 AI 分析，也不启用远程后端。

## 验证标准

- 冷 AX 耗时大于 200ms、小于 750ms 时，worker 仍能在重放前冻结帧。
- AX 或截图超过 750ms 时，watchdog 只重放一组 keyDown/keyUp，不吞键、不重复发送。
- 可信的两行 Vision 文本能通过识别并进入既有物理按键数校验；空文本、边缘裁切、输入法预编辑和超长文本仍被拒绝。
- secure、ignored、count-only 路径不截图。
- 全量测试、静态检查和独立 Critical/Important 评审通过。
- 合并、推送和重启后，用 Kim 与微信分别发送一条超过一行的唯一测试文本；数据库正文完整，来源分别为 `kim_presubmit_ocr` 与 `wechat_presubmit_ocr`，服务 PID 和心跳稳定。
