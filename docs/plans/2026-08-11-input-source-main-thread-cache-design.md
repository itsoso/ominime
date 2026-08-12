# macOS 输入源主线程缓存设计

## 背景与根因

OminiMe 为了判断豆包输入法候选和 Kim/微信 OCR 内容是否可信，会调用 Carbon HIToolbox 的 `TISCopyCurrentKeyboardInputSource` 与 `TISGetInputSourceProperty`。这些调用当前发生在键盘事件工作线程和 EventTap run-loop 线程。

macOS 26.4.1 的 Python 崩溃报告显示，进程以 `EXC_BREAKPOINT / SIGTRAP` 退出。触发线程为 `_event_worker_loop` 或 `_run_loop_thread`，原生栈固定经过 `_dispatch_assert_queue_fail -> TSMGetInputSourceProperty`。这是系统框架的队列断言，不会转换成 Python 异常，因此 `try/except` 无法避免进程崩溃。LaunchAgent 的 KeepAlive 会反复重启进程，现场已累计连续崩溃。

## 目标

- 只允许 AppKit 主线程调用原生 TIS 输入源 API。
- 键盘事件、候选读取、画面冻结和 OCR 线程只读取 Python 缓存。
- 输入源缓存缺失或过期时保守降级，不能用陈旧的豆包身份放宽正文信任。
- 不改变 Kim/微信应用身份、物理键数量、候选位置或 OCR 内容校验。
- 启动、停止和重复启动时不泄漏计时器或后台任务。

## 方案比较

### 方案 A：AppKit 主线程定时刷新缓存（采用）

菜单栏应用在主线程创建短周期计时器。计时器调用原生 TIS API，把 Bundle ID 和单调时钟时间写入模块级缓存。消费者只读取缓存；缓存超过有效期就返回空字符串。

优点是线程边界明确、实现小、失败保守，而且不依赖未公开通知。250ms 刷新周期足够覆盖正常输入法切换，缓存有效期略大于刷新周期以容忍一次主线程延迟。

### 方案 B：监听输入源变更通知

变更时才刷新，开销更低，但 Carbon/分布式通知在不同 macOS 版本和 Python 桥接方式下行为不够稳定，需要额外处理启动时初值、通知遗漏和线程投递。

### 方案 C：后台线程同步派发到主队列

输入源最实时，但 EventTap 或工作线程会同步等待主线程。菜单交互或系统阻塞时可能导致 EventTap 超时、死锁或输入延迟，不采用。

## 组件与数据流

1. `ime_candidate_capture` 保留一个线程安全的输入源快照：Bundle ID、刷新时间。
2. `refresh_input_source_cache()` 断言当前线程是 Python 主线程，然后调用现有原生 TIS 读取函数并更新快照。读取失败时写入空值，不静默保留可能错误的旧身份。
3. `cached_input_source_bundle_id()` 只读取快照；未初始化或超过有效期时返回空字符串。
4. `DoubaoCandidateReader` 和 `KimPreSubmitCapture` 的默认 provider 改为缓存读取函数。测试注入的 provider 保持不变。
5. `OmniMeMenuBarApp` 在主线程初始化时先刷新一次，再启动 250ms 的 `rumps.Timer`。退出时停止计时器。
6. 如果主线程短暂繁忙导致缓存过期，候选和 OCR 返回“不确认输入源”的保守结果；下一次刷新后自动恢复。

## 测试与验收

- 缓存未初始化、过期和刷新失败时均返回空字符串。
- 主线程刷新会调用原生 provider 并发布新快照。
- 后台线程调用刷新函数会被拒绝，且不触发原生 provider。
- `DoubaoCandidateReader` 与 `KimPreSubmitCapture` 默认路径只调用缓存 provider。
- 菜单栏应用创建并启动刷新计时器，退出时停止。
- 定向测试与全量测试通过。
- 部署后 LaunchAgent PID 稳定，`successive crashes` 不继续增长；部署时间之后没有新的 Python `.ips` 报告。

## 发布与回滚

这是本机 Python 源码更新，LaunchAgent 直接从仓库 `src` 加载。合并后重启 `com.ominime.app`。若健康检查或稳定性验证失败，回滚该提交并再次 kickstart；数据库格式不变，无数据迁移。

