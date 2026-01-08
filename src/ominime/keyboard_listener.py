"""
键盘监听模块

使用 CGEventTap 监听全局键盘事件
支持中文输入法
需要用户授予辅助功能权限
"""

import threading
import time
import ctypes
import ctypes.util
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime

# macOS 原生 API
from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventGetIntegerValueField,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventKeyDown,
    kCGEventFlagsChanged,
    kCGKeyboardEventKeycode,
    kCGEventFlagMaskShift,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    CGEventGetFlags,
)
from AppKit import NSWorkspace, NSEvent
import Quartz


@dataclass
class KeyEvent:
    """按键事件"""
    timestamp: datetime
    keycode: int
    character: str
    app_name: str
    app_bundle_id: str
    modifiers: dict  # shift, ctrl, alt, cmd


# 特殊键码映射（这些键不需要通过输入法转换）
SPECIAL_KEYCODE_MAP = {
    # 特殊键
    36: '\n',     # Return
    48: '\t',     # Tab
    49: ' ',      # Space
    51: '\b',     # Delete (Backspace)
    53: 'esc',    # Escape
    117: 'del',   # Forward Delete
    
    # 方向键
    123: '←', 124: '→', 125: '↓', 126: '↑',
    
    # 功能键
    122: 'F1', 120: 'F2', 99: 'F3', 118: 'F4', 96: 'F5', 97: 'F6',
    98: 'F7', 100: 'F8', 101: 'F9', 109: 'F10', 103: 'F11', 111: 'F12',
    
    # 数字小键盘特殊键
    71: 'clear', 76: '\n',  # clear, keypad enter
}

# 忽略的键码（修饰键等）
IGNORED_KEYCODES = {
    54, 55,   # Command
    56, 60,   # Shift
    58, 61,   # Option/Alt
    59, 62,   # Control
    57,       # Caps Lock
    63,       # fn
}


class KeyboardListener:
    """
    全局键盘监听器
    
    使用 CGEventTap 监听所有键盘事件
    支持中文输入法
    """
    
    def __init__(self, callback: Callable[[KeyEvent], None]):
        """
        初始化监听器
        
        Args:
            callback: 按键事件回调函数
        """
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._run_loop = None
        self._tap = None
    
    def _get_active_app(self) -> tuple[str, str]:
        """获取当前活跃的应用"""
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        if active_app:
            return (
                active_app.localizedName() or "Unknown",
                active_app.bundleIdentifier() or "unknown"
            )
        return ("Unknown", "unknown")
    
    def _get_unicode_string(self, event) -> str:
        """
        从 CGEvent 获取 Unicode 字符串（支持中文）
        
        使用 NSEvent 来获取经过输入法处理后的字符
        """
        try:
            # 将 CGEvent 转换为 NSEvent
            ns_event = NSEvent.eventWithCGEvent_(event)
            if ns_event:
                # 获取字符（经过输入法处理）
                chars = ns_event.characters()
                if chars and len(chars) > 0:
                    return chars
        except Exception as e:
            pass
        
        return ""
    
    def _event_callback(self, proxy, event_type, event, refcon):
        """CGEventTap 回调函数"""
        if event_type == kCGEventKeyDown:
            try:
                # 获取键码
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                
                # 忽略修饰键
                if keycode in IGNORED_KEYCODES:
                    return event
                
                # 获取修饰键状态
                flags = CGEventGetFlags(event)
                modifiers = {
                    "shift": bool(flags & kCGEventFlagMaskShift),
                    "ctrl": bool(flags & kCGEventFlagMaskControl),
                    "alt": bool(flags & kCGEventFlagMaskAlternate),
                    "cmd": bool(flags & kCGEventFlagMaskCommand),
                }
                
                # 获取字符
                character = ""
                
                # 首先检查是否是特殊键
                if keycode in SPECIAL_KEYCODE_MAP:
                    character = SPECIAL_KEYCODE_MAP[keycode]
                else:
                    # 使用 NSEvent 获取实际输入的字符（支持中文）
                    character = self._get_unicode_string(event)
                
                # 如果没有获取到字符，跳过
                if not character:
                    return event
                
                # 获取当前活跃应用
                app_name, app_bundle_id = self._get_active_app()
                
                # 创建事件对象
                key_event = KeyEvent(
                    timestamp=datetime.now(),
                    keycode=keycode,
                    character=character,
                    app_name=app_name,
                    app_bundle_id=app_bundle_id,
                    modifiers=modifiers,
                )
                
                # 调用回调
                if self.callback:
                    self.callback(key_event)
                    
            except Exception as e:
                print(f"Error processing key event: {e}")
        
        return event
    
    def _run_loop_thread(self):
        """在独立线程中运行事件循环"""
        # 创建事件 mask
        event_mask = (1 << kCGEventKeyDown)
        
        # 创建 CGEventTap
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,      # 监听会话级别的事件
            kCGHeadInsertEventTap,   # 在事件链头部插入
            0,                        # 0 = 活跃 tap, 1 = 被动 tap
            event_mask,              # 要监听的事件类型
            self._event_callback,    # 回调函数
            None                      # 用户数据
        )
        
        if self._tap is None:
            print("❌ 无法创建 CGEventTap")
            print("请确保已授予辅助功能权限：")
            print("系统偏好设置 → 隐私与安全性 → 辅助功能")
            return
        
        # 创建运行循环源
        run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._run_loop = CFRunLoopGetCurrent()
        
        # 将源添加到运行循环
        CFRunLoopAddSource(self._run_loop, run_loop_source, Quartz.kCFRunLoopCommonModes)
        
        # 启用 tap
        CGEventTapEnable(self._tap, True)
        
        print("✅ 键盘监听已启动（支持中文输入）")
        
        # 运行事件循环
        CFRunLoopRun()
    
    def start(self):
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop_thread, daemon=True)
        self._thread.start()
    
    def stop(self):
        """停止监听"""
        if not self._running:
            return
        
        self._running = False
        
        if self._tap:
            CGEventTapEnable(self._tap, False)
        
        if self._run_loop:
            CFRunLoopStop(self._run_loop)
        
        if self._thread:
            self._thread.join(timeout=1.0)
        
        print("⏹️ 键盘监听已停止")
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running


def check_accessibility_permission() -> bool:
    """
    检查是否有辅助功能权限
    
    Returns:
        bool: 是否有权限
    """
    from ApplicationServices import AXIsProcessTrusted
    return AXIsProcessTrusted()


def request_accessibility_permission():
    """
    请求辅助功能权限
    
    这会打开系统偏好设置中的辅助功能页面
    """
    from ApplicationServices import AXIsProcessTrustedWithOptions
    from Foundation import NSDictionary
    
    options = NSDictionary.dictionaryWithObject_forKey_(
        True,
        "AXTrustedCheckOptionPrompt"
    )
    AXIsProcessTrustedWithOptions(options)


# 测试代码
if __name__ == "__main__":
    print("🔍 检查辅助功能权限...")
    
    if not check_accessibility_permission():
        print("❌ 没有辅助功能权限，正在请求...")
        request_accessibility_permission()
        print("请在系统偏好设置中授予权限后重新运行")
        exit(1)
    
    print("✅ 已获得辅助功能权限")
    print("🇨🇳 已启用中文输入支持")
    
    def on_key(event: KeyEvent):
        char = event.character if event.character else f"[{event.keycode}]"
        # 特殊字符处理
        if char == '\n':
            print()
        elif char == '\b':
            print('\b \b', end='', flush=True)
        elif char in ['esc', '←', '→', '↑', '↓', 'del']:
            pass  # 忽略这些键
        else:
            print(f"{char}", end="", flush=True)
    
    listener = KeyboardListener(on_key)
    listener.start()
    
    print("\n按 Ctrl+C 停止监听...")
    print("-" * 40)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        print("\n已停止")
