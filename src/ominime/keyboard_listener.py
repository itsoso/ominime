"""
键盘监听模块

方案：
1. CGEventTap 监听键盘事件（英文、数字、符号、特殊键）
2. Rime 日志监听（中文输入法）
3. 系统唤醒事件监听，自动恢复 CGEventTap

需要用户授予辅助功能权限
"""

import threading
import time
import re
import uuid
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import queue

# macOS 原生 API
from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventTapIsEnabled,
    CFMachPortIsValid,
    CGEventGetIntegerValueField,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopRemoveSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    kCGKeyboardEventKeycode,
    kCGEventFlagMaskShift,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    CGEventGetFlags,
)
from AppKit import NSWorkspace, NSRunningApplication
from Foundation import NSObject, NSRunLoop, NSDefaultRunLoopMode, NSDistributedNotificationCenter
import Quartz
import objc

from .config import config
from .context_capture import capture_accessibility_context, context_to_dict
from .input_snapshot import normalize_submission_text
from .screenshot_capture import capture_context_screenshot


@dataclass
class KeyEvent:
    """按键事件"""
    timestamp: datetime
    keycode: int
    character: str
    app_name: str
    app_bundle_id: str
    modifiers: dict
    is_ime_input: bool = False


# 键码映射
SPECIAL_KEYCODE_MAP = {
    36: '\n', 48: '\t', 49: ' ', 51: '\b', 53: 'esc', 117: 'del',
    123: '←', 124: '→', 125: '↓', 126: '↑',
    122: 'F1', 120: 'F2', 99: 'F3', 118: 'F4', 96: 'F5', 97: 'F6',
    98: 'F7', 100: 'F8', 101: 'F9', 109: 'F10', 103: 'F11', 111: 'F12',
}

IGNORED_KEYCODES = {54, 55, 56, 60, 58, 61, 59, 62, 57, 63}

KEYCODE_TO_CHAR = {
    0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x',
    8: 'c', 9: 'v', 11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r',
    16: 'y', 17: 't', 18: '1', 19: '2', 20: '3', 21: '4', 22: '6',
    23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8', 29: '0',
    30: ']', 31: 'o', 32: 'u', 33: '[', 34: 'i', 35: 'p', 37: 'l',
    38: 'j', 39: "'", 40: 'k', 41: ';', 42: '\\', 43: ',', 44: '/',
    45: 'n', 46: 'm', 47: '.', 50: '`',
}


# 全局变量：当前活跃应用（通过应用切换通知更新）
_current_app_name = "Unknown"
_current_app_bundle = "unknown"
_app_lock = threading.Lock()
_DEBUG = False  # 调试模式
_app_watcher_started = False

# 最近接收键盘输入的应用（用于 Rime 中文输入归属）
_last_input_app_name = "Unknown"
_last_input_app_bundle = "unknown"
_last_input_lock = threading.Lock()

# 拼音检测：用于判断是否正在输入拼音
_pinyin_mode = False
_pinyin_mode_lock = threading.Lock()

# 拼音缓冲区：缓存可能是拼音的字母，如果没有 Rime 输出则作为英文处理
_pinyin_buffer = ""
_pinyin_buffer_app = ("Unknown", "unknown")
_pinyin_buffer_lock = threading.Lock()

# 只在 Enter 提交时读取完整输入框内容，避免记录拼音中间态。
ENTER_KEYCODE = 36


def set_last_input_app(name: str, bundle_id: str):
    """设置最近接收键盘输入的应用"""
    global _last_input_app_name, _last_input_app_bundle
    with _last_input_lock:
        _last_input_app_name = name
        _last_input_app_bundle = bundle_id


def get_last_input_app() -> tuple[str, str]:
    """获取最近接收键盘输入的应用"""
    with _last_input_lock:
        return (_last_input_app_name, _last_input_app_bundle)


def add_to_pinyin_buffer(char: str, app_name: str, bundle_id: str):
    """添加字符到拼音缓冲区"""
    global _pinyin_buffer, _pinyin_buffer_app
    with _pinyin_buffer_lock:
        _pinyin_buffer += char
        _pinyin_buffer_app = (app_name, bundle_id)


def clear_pinyin_buffer():
    """清空拼音缓冲区（Rime 已输出中文）"""
    global _pinyin_buffer
    with _pinyin_buffer_lock:
        _pinyin_buffer = ""


def flush_pinyin_buffer_as_english() -> tuple[str, str, str]:
    """将拼音缓冲区作为英文输出并清空，返回 (内容, app_name, bundle_id)"""
    global _pinyin_buffer, _pinyin_buffer_app
    with _pinyin_buffer_lock:
        content = _pinyin_buffer
        app = _pinyin_buffer_app
        _pinyin_buffer = ""
        return (content, app[0], app[1])


def set_pinyin_mode(is_pinyin: bool):
    """设置拼音输入模式"""
    global _pinyin_mode
    with _pinyin_mode_lock:
        _pinyin_mode = is_pinyin


def is_pinyin_mode() -> bool:
    """检查是否在拼音输入模式"""
    with _pinyin_mode_lock:
        return _pinyin_mode


def _on_app_activated(name: str, bundle_id: str):
    """应用切换回调"""
    global _current_app_name, _current_app_bundle
    with _app_lock:
        if _DEBUG:
            print(f"[DEBUG] 应用切换: {_current_app_name} -> {name} ({bundle_id})")
        _current_app_name = name
        _current_app_bundle = bundle_id


def _start_app_watcher():
    """启动应用切换监听器（在单独线程中运行）"""
    global _app_watcher_started, _current_app_name, _current_app_bundle
    
    if _app_watcher_started:
        return
    _app_watcher_started = True
    
    from Foundation import NSDate
    
    # 创建监听器类
    class AppWatcher(NSObject):
        def init(self):
            self = objc.super(AppWatcher, self).init()
            return self
        
        def applicationActivated_(self, notification):
            try:
                app = notification.userInfo()["NSWorkspaceApplicationKey"]
                name = app.localizedName() or "Unknown"
                bundle_id = app.bundleIdentifier() or "unknown"
                _on_app_activated(name, bundle_id)
            except Exception as e:
                if _DEBUG:
                    print(f"[DEBUG] App watcher error: {e}")
    
    def run_watcher():
        watcher = AppWatcher.alloc().init()
        
        # 获取 workspace notification center
        ws = NSWorkspace.sharedWorkspace()
        nc = ws.notificationCenter()
        
        # 监听应用激活事件
        nc.addObserver_selector_name_object_(
            watcher,
            objc.selector(watcher.applicationActivated_, signature=b'v@:@'),
            "NSWorkspaceDidActivateApplicationNotification",
            None
        )
        
        # 初始化当前应用
        front_app = ws.frontmostApplication()
        if front_app:
            _on_app_activated(
                front_app.localizedName() or "Unknown",
                front_app.bundleIdentifier() or "unknown"
            )
        
        # 运行 RunLoop（应用切换由系统通知驱动）
        # 注意: runMode_beforeDate_ 可能在有 ready source 时立即返回，
        # 必须加 sleep 防止在 Rosetta 翻译下忙循环
        run_loop = NSRunLoop.currentRunLoop()
        while True:
            run_loop.runMode_beforeDate_(NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(1.0))
            time.sleep(0.1)  # 防止 RunLoop 立即返回导致忙循环
    
    thread = threading.Thread(target=run_watcher, daemon=True)
    thread.start()
    
    # 等待初始化完成
    time.sleep(0.2)


def get_frontmost_app() -> tuple[str, str]:
    """获取当前最前台的应用（直接调用 API）"""
    try:
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        if app:
            name = app.localizedName() or "Unknown"
            bundle_id = app.bundleIdentifier() or "unknown"
            return (name, bundle_id)
    except Exception as e:
        if _DEBUG:
            print(f"[DEBUG] get_frontmost_app error: {e}")
    return ("Unknown", "unknown")


def get_app_by_pid(pid: int) -> tuple[str, str]:
    """根据进程 ID 获取应用信息"""
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app:
            name = app.localizedName() or "Unknown"
            bundle_id = app.bundleIdentifier() or "unknown"
            return (name, bundle_id)
    except Exception as e:
        if _DEBUG:
            print(f"[DEBUG] get_app_by_pid error: {e}")
    return get_frontmost_app()  # 回退到 frontmost


def get_current_app() -> tuple[str, str]:
    """获取当前应用（从缓存读取，由应用切换通知更新）"""
    with _app_lock:
        return (_current_app_name, _current_app_bundle)


def get_current_app_fresh() -> tuple[str, str]:
    """获取当前应用（优先使用缓存，缓存无效时直接查询）"""
    with _app_lock:
        if _current_app_name != "Unknown":
            return (_current_app_name, _current_app_bundle)
    # 缓存无效，直接查询
    return get_frontmost_app()


class RimeLogWatcher:
    """监听 Rime 输入法日志文件"""
    
    RIME_LOG_PATH = Path.home() / ".ominime" / "rime_input.log"
    
    def __init__(self, callback: Callable[[str, datetime, str, str], None]):
        """callback: (text, timestamp, app_name, bundle_id) -> None"""
        self.callback = callback
        self._running = False
        self._thread = None
        self._last_position = 0
        self._last_mtime = 0
    
    def _ensure_log_file(self):
        self.RIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not self.RIME_LOG_PATH.exists():
            self.RIME_LOG_PATH.touch()
    
    def _parse_content(self, content: str) -> str:
        text = re.sub(r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]', '', content)
        return text
    
    def _watch_loop(self):
        self._ensure_log_file()
        
        try:
            self._last_position = self.RIME_LOG_PATH.stat().st_size
            self._last_mtime = self.RIME_LOG_PATH.stat().st_mtime
        except:
            self._last_position = 0
            self._last_mtime = 0
        
        while self._running:
            try:
                try:
                    current_mtime = self.RIME_LOG_PATH.stat().st_mtime
                except:
                    time.sleep(0.1)
                    continue
                
                if current_mtime > self._last_mtime:
                    self._last_mtime = current_mtime
                    
                    # 使用最近接收键盘输入的应用（拼音输入时记录的目标应用）
                    app_name, bundle_id = get_last_input_app()
                    if app_name == "Unknown":
                        # 如果没有记录，回退到 frontmost
                        app_name, bundle_id = get_frontmost_app()
                    
                    with open(self.RIME_LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(self._last_position)
                        new_content = f.read()
                        self._last_position = f.tell()
                    
                    if new_content:
                        text = self._parse_content(new_content)
                        if text and self.callback:
                            if _DEBUG:
                                print(f"[DEBUG] Rime 输入: '{text}' -> {app_name} ({bundle_id})")
                            self.callback(text, datetime.now(), app_name, bundle_id)
                
                time.sleep(0.3)
            except Exception as e:
                if _DEBUG:
                    print(f"[DEBUG] Rime watch error: {e}")
                time.sleep(1.0)
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)


class KeyboardListener:
    """全局键盘监听器

    包含以下健壮性机制：
    1. 定期健康检查 CGEventTap 状态
    2. 监听系统唤醒事件，自动恢复
    3. 自动重连机制
    """

    # 健康检查间隔（秒）
    HEALTH_CHECK_INTERVAL = 30
    # 最大重试次数
    MAX_RETRY_COUNT = 3

    def __init__(self, callback: Callable[[KeyEvent], None]):
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._health_check_thread: Optional[threading.Thread] = None
        self._run_loop = None
        self._run_loop_source = None
        self._tap = None
        self._rime_watcher = RimeLogWatcher(self._on_rime_input)
        self._last_event_time = time.time()
        self._tap_lock = threading.Lock()
        self._retry_count = 0
        self._wake_observer = None
    
    def _on_rime_input(self, text: str, timestamp: datetime, app_name: str, bundle_id: str):
        """Rime log events are ignored in submission-snapshot mode."""
        return

    def _copy_ax_attribute(self, element, attribute: str):
        """Read an Accessibility attribute across PyObjC signature variants."""
        try:
            from ApplicationServices import AXUIElementCopyAttributeValue

            try:
                result = AXUIElementCopyAttributeValue(element, attribute, None)
            except TypeError:
                result = AXUIElementCopyAttributeValue(element, attribute)

            if isinstance(result, tuple):
                if len(result) >= 2 and result[0] == 0:
                    return result[1]
                return None
            return result
        except Exception as e:
            if _DEBUG:
                print(f"[DEBUG] AX read attribute failed: {attribute}: {e}")
            return None

    def _get_focused_text_snapshot(self) -> str:
        """Read current focused input value for IME/voice commit diffing."""
        try:
            from ApplicationServices import AXUIElementCreateSystemWide

            system = AXUIElementCreateSystemWide()
            focused = self._copy_ax_attribute(system, "AXFocusedUIElement")
            if focused is None:
                return ""

            value = self._copy_ax_attribute(focused, "AXValue")
            if isinstance(value, str):
                return value
        except Exception as e:
            if _DEBUG:
                print(f"[DEBUG] focused text snapshot failed: {e}")
        return ""

    def _get_event_target_app(self, event) -> tuple[str, str]:
        target_pid = CGEventGetIntegerValueField(event, 40)  # kCGEventTargetUnixProcessID
        if target_pid > 0:
            return get_app_by_pid(target_pid)
        return get_frontmost_app()

    def _emit_submission_snapshot(self, event):
        """Emit the full focused input value when Enter is pressed."""
        app_name, bundle_id = self._get_event_target_app(event)
        content = normalize_submission_text(self._get_focused_text_snapshot())
        if not content:
            return

        submission_id = uuid.uuid4().hex
        context_data = {}
        screenshot_data = {"status": "disabled", "scope": None, "path": None, "error": None}
        if config.capture_context_on_enter:
            context = capture_accessibility_context()
            context_data = context_to_dict(context)
            if (
                config.capture_dialog_screenshot
                and bundle_id not in config.screenshot_ignored_apps
            ):
                screenshot = capture_context_screenshot(
                    context,
                    submission_id=submission_id,
                    timestamp=datetime.now(),
                    base_dir=config.data_dir / "screenshots",
                    max_width=config.screenshot_max_width,
                )
                screenshot_data = {
                    "status": screenshot.status,
                    "scope": screenshot.scope,
                    "path": str(screenshot.path) if screenshot.path else None,
                    "error": screenshot.error,
                }

        if _DEBUG:
            print(f"[DEBUG] Enter 提交快照: {len(content)} chars -> {app_name}")

        modifiers = {
            "shift": False,
            "ctrl": False,
            "alt": False,
            "cmd": False,
            "submit_snapshot": True,
            "submission_id": submission_id,
            "context": context_data,
            "screenshot": screenshot_data,
        }
        key_event = KeyEvent(
            timestamp=datetime.now(),
            keycode=ENTER_KEYCODE,
            character=content,
            app_name=app_name,
            app_bundle_id=bundle_id,
            modifiers=modifiers,
            is_ime_input=True,
        )
        if self.callback:
            self.callback(key_event)
    
    def _event_callback(self, proxy, event_type, event, refcon):
        """CGEventTap 回调"""
        if event_type == kCGEventKeyDown:
            try:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                if keycode == ENTER_KEYCODE:
                    self._emit_submission_snapshot(event)
            except Exception:
                pass
        
        return event
    
    def _create_event_tap(self) -> bool:
        """创建 CGEventTap，返回是否成功"""
        with self._tap_lock:
            # 清理旧的 tap
            if self._tap is not None:
                try:
                    CGEventTapEnable(self._tap, False)
                except:
                    pass
                self._tap = None

            event_mask = (1 << kCGEventKeyDown)

            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                0,
                event_mask,
                self._event_callback,
                None
            )

            if self._tap is None:
                print("❌ 无法创建 CGEventTap")
                print("请确保已授予辅助功能权限")
                return False

            return True

    def _is_tap_healthy(self) -> bool:
        """检查 CGEventTap 是否健康"""
        with self._tap_lock:
            if self._tap is None:
                return False
            try:
                # 检查 MachPort 是否有效
                if not CFMachPortIsValid(self._tap):
                    print("⚠️  CGEventTap MachPort 无效")
                    return False
                # 检查 tap 是否启用
                if not CGEventTapIsEnabled(self._tap):
                    print("⚠️  CGEventTap 已被禁用，尝试重新启用...")
                    CGEventTapEnable(self._tap, True)
                    # 再次检查
                    if not CGEventTapIsEnabled(self._tap):
                        print("❌ 无法重新启用 CGEventTap")
                        return False
                    print("✅ CGEventTap 已重新启用")
                return True
            except Exception as e:
                print(f"⚠️  检查 CGEventTap 状态失败: {e}")
                return False

    def _health_check_loop(self):
        """健康检查循环"""
        while self._running:
            time.sleep(self.HEALTH_CHECK_INTERVAL)
            if not self._running:
                break

            if not self._is_tap_healthy():
                print("🔄 CGEventTap 不健康，尝试重建...")
                self._rebuild_tap()

    def _rebuild_tap(self):
        """重建 CGEventTap"""
        if self._retry_count >= self.MAX_RETRY_COUNT:
            print(f"❌ 已达到最大重试次数 ({self.MAX_RETRY_COUNT})，停止重试")
            return

        self._retry_count += 1
        print(f"🔄 第 {self._retry_count} 次尝试重建 CGEventTap...")

        with self._tap_lock:
            # 移除旧的 source
            if self._run_loop_source and self._run_loop:
                try:
                    CFRunLoopRemoveSource(self._run_loop, self._run_loop_source, Quartz.kCFRunLoopCommonModes)
                except:
                    pass
                self._run_loop_source = None

        # 创建新的 tap
        if self._create_event_tap():
            with self._tap_lock:
                self._run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
                if self._run_loop:
                    CFRunLoopAddSource(self._run_loop, self._run_loop_source, Quartz.kCFRunLoopCommonModes)
                    CGEventTapEnable(self._tap, True)
                    print("✅ CGEventTap 重建成功")
                    self._retry_count = 0  # 重置重试计数
        else:
            print("❌ CGEventTap 重建失败")

    def _on_system_wake(self, notification):
        """系统唤醒回调"""
        print("💤 检测到系统唤醒，检查 CGEventTap 状态...")
        # 延迟一下再检查，等系统完全唤醒
        def delayed_check():
            time.sleep(2)
            if self._running and not self._is_tap_healthy():
                print("🔄 系统唤醒后 CGEventTap 失效，尝试重建...")
                self._rebuild_tap()
            else:
                print("✅ 系统唤醒后 CGEventTap 状态正常")
        threading.Thread(target=delayed_check, daemon=True).start()

    def _start_wake_observer(self):
        """启动系统唤醒事件监听"""
        try:
            ws = NSWorkspace.sharedWorkspace()
            nc = ws.notificationCenter()

            # 创建观察者类
            class WakeObserver(NSObject):
                def init(self_inner):
                    self_inner = objc.super(WakeObserver, self_inner).init()
                    return self_inner

                def onWake_(self_inner, notification):
                    self._on_system_wake(notification)

            self._wake_observer = WakeObserver.alloc().init()

            # 监听系统唤醒事件
            nc.addObserver_selector_name_object_(
                self._wake_observer,
                objc.selector(self._wake_observer.onWake_, signature=b'v@:@'),
                "NSWorkspaceDidWakeNotification",
                None
            )
            print("👁️  系统唤醒监听已启动")
        except Exception as e:
            print(f"⚠️  启动系统唤醒监听失败: {e}")

    def _run_loop_thread(self):
        if not self._create_event_tap():
            return

        with self._tap_lock:
            self._run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._run_loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(self._run_loop, self._run_loop_source, Quartz.kCFRunLoopCommonModes)
            CGEventTapEnable(self._tap, True)

        print("✅ 键盘监听已启动")
        print("📝 Enter 提交快照监听已启动")

        # 使用带超时的循环代替 CFRunLoopRun()，
        # 避免 Rosetta 翻译下 CGEventTap 回调导致忙循环
        while self._running:
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 1.0, False)
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._retry_count = 0

        # 启动应用切换监听器（基于系统通知，比轮询更准确）
        _start_app_watcher()

        # 启动系统唤醒监听
        self._start_wake_observer()

        # 启动键盘监听
        self._thread = threading.Thread(target=self._run_loop_thread, daemon=True)
        self._thread.start()

        # 启动健康检查线程
        self._health_check_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        self._health_check_thread.start()

        # 提交快照模式不启动 Rime 日志监听，避免保存拼音中间态。

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._rime_watcher.stop()

        with self._tap_lock:
            if self._tap:
                try:
                    CGEventTapEnable(self._tap, False)
                except:
                    pass
            if self._run_loop:
                CFRunLoopStop(self._run_loop)

        if self._health_check_thread:
            self._health_check_thread.join(timeout=1.0)
        if self._thread:
            self._thread.join(timeout=1.0)

        # 移除唤醒监听
        if self._wake_observer:
            try:
                ws = NSWorkspace.sharedWorkspace()
                nc = ws.notificationCenter()
                nc.removeObserver_(self._wake_observer)
            except:
                pass
            self._wake_observer = None

        print("⏹️ 监听已停止")
    
    def is_running(self) -> bool:
        return self._running


def check_accessibility_permission() -> bool:
    from ApplicationServices import AXIsProcessTrusted
    return AXIsProcessTrusted()


def request_accessibility_permission():
    from ApplicationServices import AXIsProcessTrustedWithOptions
    from Foundation import NSDictionary
    options = NSDictionary.dictionaryWithObject_forKey_(True, "AXTrustedCheckOptionPrompt")
    AXIsProcessTrustedWithOptions(options)


if __name__ == "__main__":
    print("🔍 检查辅助功能权限...")
    
    if not check_accessibility_permission():
        print("❌ 没有辅助功能权限，正在请求...")
        request_accessibility_permission()
        print("请在系统偏好设置中授予权限后重新运行")
        exit(1)
    
    print("✅ 已获得辅助功能权限")
    print("-" * 50)
    
    last_app = [""]
    
    def on_key(event: KeyEvent):
        if last_app[0] != event.app_name:
            if last_app[0]:
                print()
            print(f"\n[{event.app_name}] ", end="", flush=True)
            last_app[0] = event.app_name
        
        char = event.character
        if char == '\n':
            print()
            print(f"[{event.app_name}] ", end="", flush=True)
        elif char == '\b':
            print('\b \b', end='', flush=True)
        elif char in ['esc', '←', '→', '↑', '↓', 'del'] or (len(char) <= 3 and char.startswith('F')):
            pass
        else:
            if event.is_ime_input:
                print(f"\033[32m{char}\033[0m", end="", flush=True)
            else:
                print(f"{char}", end="", flush=True)
    
    listener = KeyboardListener(on_key)
    listener.start()
    
    print("\n按 Ctrl+C 停止监听...")
    print("💡 中文显示为绿色\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        print("\n已停止")
