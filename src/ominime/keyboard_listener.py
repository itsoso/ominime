"""
键盘监听模块

方案：
1. CGEventTap 监听键盘事件（英文、特殊键）
2. 监听 Rime 输入法日志文件（中文输入）

需要用户授予辅助功能权限
"""

import threading
import time
import os
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    kCGKeyboardEventKeycode,
    kCGEventFlagMaskShift,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    CGEventGetFlags,
)
from AppKit import NSWorkspace
import Quartz

# Carbon API for Input Source
try:
    from Carbon import TIS
    HAS_TIS = True
except:
    HAS_TIS = False


def is_ascii_input_mode() -> bool:
    """检测当前是否是 ASCII（英文）输入模式"""
    if not HAS_TIS:
        return True  # 无法检测时默认英文
    
    try:
        source = TIS.TISCopyCurrentKeyboardInputSource()
        if source:
            # 检查 ASCII capable
            ascii_capable = TIS.TISGetInputSourceProperty(
                source, 
                TIS.kTISPropertyInputSourceIsASCIICapable
            )
            
            # 获取输入源 ID
            source_id = TIS.TISGetInputSourceProperty(
                source, 
                TIS.kTISPropertyInputSourceID
            )
            
            if source_id:
                source_str = str(source_id)
                # 检测中文输入法
                chinese_keywords = [
                    'Chinese', 'Pinyin', 'Wubi', 'Shuangpin',
                    'SCIM', 'Sogou', 'Baidu', 'QQ', 'Rime',
                    'Squirrel', 'luna_pinyin',
                ]
                is_chinese = any(kw.lower() in source_str.lower() for kw in chinese_keywords)
                
                if is_chinese:
                    # 中文输入法 - 需要进一步检测是否在英文模式
                    # Rime 英文模式通常会切换到不同的 source
                    if 'ascii' in source_str.lower() or 'ABC' in source_str:
                        return True
                    return False
                else:
                    return True  # 非中文输入法，直接输出
    except Exception:
        pass
    return True  # 默认英文模式


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


class RimeLogWatcher:
    """
    监听 Rime 输入法日志文件
    用于获取中文输入内容
    新格式: [时间]文字[时间]文字...（连续，无空格）
    """
    
    RIME_LOG_PATH = Path.home() / ".ominime" / "rime_input.log"
    
    def __init__(self, callback: Callable[[str, datetime], None]):
        """
        callback: (text, timestamp) -> None
        """
        self.callback = callback
        self._running = False
        self._thread = None
        self._last_position = 0
        self._last_mtime = 0
    
    def _ensure_log_file(self):
        """确保日志文件存在"""
        self.RIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not self.RIME_LOG_PATH.exists():
            self.RIME_LOG_PATH.touch()
    
    def _parse_content(self, content: str):
        """
        解析日志内容
        格式: [2024-01-08 12:00:00]你好[2024-01-08 12:00:01]世界
        提取: 你好世界
        """
        import re
        # 移除时间戳标记，只保留文字
        # 匹配 [YYYY-MM-DD HH:MM:SS] 格式
        text = re.sub(r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]', '', content)
        return text
    
    def _watch_loop(self):
        """监听循环"""
        self._ensure_log_file()
        
        # 初始化位置到文件末尾（忽略历史记录）
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
                    
                    # 读取新增内容
                    with open(self.RIME_LOG_PATH, 'r', encoding='utf-8') as f:
                        f.seek(self._last_position)
                        new_content = f.read()
                        self._last_position = f.tell()
                    
                    if new_content:
                        # 解析并提取纯文字
                        text = self._parse_content(new_content)
                        if text and self.callback:
                            self.callback(text, datetime.now())
                
                time.sleep(0.1)
            except Exception as e:
                time.sleep(0.5)
    
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
    
    def clear_log(self):
        """清空日志文件"""
        try:
            with open(self.RIME_LOG_PATH, 'w') as f:
                pass
            self._last_position = 0
        except:
            pass


class KeyboardListener:
    """
    全局键盘监听器
    
    结合 CGEventTap + Rime 日志监听，支持中英文输入
    """
    
    def __init__(self, callback: Callable[[KeyEvent], None]):
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._run_loop = None
        self._tap = None
        
        # Rime 日志监听
        self._rime_watcher = RimeLogWatcher(self._on_rime_input)
        self._current_app = ("Unknown", "unknown")
    
    def _get_active_app(self) -> tuple[str, str]:
        try:
            workspace = NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            if active_app:
                return (
                    active_app.localizedName() or "Unknown",
                    active_app.bundleIdentifier() or "unknown"
                )
        except:
            pass
        return ("Unknown", "unknown")
    
    def _on_rime_input(self, text: str, timestamp: datetime):
        """Rime 输入回调"""
        app_name, bundle_id = self._get_active_app()
        
        # 为每个字符创建事件
        for char in text:
            key_event = KeyEvent(
                timestamp=timestamp,
                keycode=-1,
                character=char,
                app_name=app_name,
                app_bundle_id=bundle_id,
                modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
                is_ime_input=True,
            )
            if self.callback:
                self.callback(key_event)
    
    def _event_callback(self, proxy, event_type, event, refcon):
        """CGEventTap 回调"""
        if event_type == kCGEventKeyDown:
            try:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                
                if keycode in IGNORED_KEYCODES:
                    return event
                
                flags = CGEventGetFlags(event)
                modifiers = {
                    "shift": bool(flags & kCGEventFlagMaskShift),
                    "ctrl": bool(flags & kCGEventFlagMaskControl),
                    "alt": bool(flags & kCGEventFlagMaskAlternate),
                    "cmd": bool(flags & kCGEventFlagMaskCommand),
                }
                
                if modifiers["cmd"]:
                    return event
                
                # 获取字符
                character = ""
                if keycode in SPECIAL_KEYCODE_MAP:
                    character = SPECIAL_KEYCODE_MAP[keycode]
                elif keycode in KEYCODE_TO_CHAR:
                    char = KEYCODE_TO_CHAR[keycode]
                    character = char.upper() if modifiers["shift"] else char
                
                if not character:
                    return event
                
                # 字母键处理：
                # - 英文模式：直接记录
                # - 中文模式：跳过（由 Rime 日志处理最终输出）
                if character.isalpha() and len(character) == 1:
                    if not is_ascii_input_mode():
                        return event  # 中文模式，跳过拼音字母
                
                app_name, bundle_id = self._get_active_app()
                
                key_event = KeyEvent(
                    timestamp=datetime.now(),
                    keycode=keycode,
                    character=character,
                    app_name=app_name,
                    app_bundle_id=bundle_id,
                    modifiers=modifiers,
                    is_ime_input=False,
                )
                
                if self.callback:
                    self.callback(key_event)
                    
            except Exception as e:
                pass
        
        return event
    
    def _run_loop_thread(self):
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
            print("请确保已授予辅助功能权限：")
            print("系统偏好设置 → 隐私与安全性 → 辅助功能")
            return
        
        run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._run_loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._run_loop, run_loop_source, Quartz.kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        
        print("✅ 键盘监听已启动")
        print("🇨🇳 Rime 中文输入监听已启动")
        
        CFRunLoopRun()
    
    def start(self):
        if self._running:
            return
        self._running = True
        # 启动键盘监听
        self._thread = threading.Thread(target=self._run_loop_thread, daemon=True)
        self._thread.start()
        # 启动 Rime 日志监听
        self._rime_watcher.start()
    
    def stop(self):
        if not self._running:
            return
        self._running = False
        self._rime_watcher.stop()
        if self._tap:
            CGEventTapEnable(self._tap, False)
        if self._run_loop:
            CFRunLoopStop(self._run_loop)
        if self._thread:
            self._thread.join(timeout=1.0)
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
    print("-" * 40)
    print("📝 记录最终输出内容：")
    print("   • 中文模式 → 记录中文（来自 Rime）")
    print("   • 英文模式 → 记录英文字母")
    print("   • 数字、符号、特殊键 → 始终记录")
    print("-" * 40)
    
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
        elif char in ['esc', '←', '→', '↑', '↓', 'del'] or (char.startswith('F') and len(char) <= 3):
            pass
        else:
            print(f"{char}", end="", flush=True)
    
    listener = KeyboardListener(on_key)
    listener.start()
    
    print("\n按 Ctrl+C 停止监听...\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        print("\n已停止")
