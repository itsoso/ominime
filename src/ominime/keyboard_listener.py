"""
输入监听模块

方案：使用 Accessibility API 监听文本框内容变化
直接获取最终输入到输入框中的内容

需要用户授予辅助功能权限
"""

import threading
import time
import re
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# macOS 原生 API
from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateSystemWide,
    AXUIElementCopyAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXValueAttribute,
    kAXRoleAttribute,
)


@dataclass
class KeyEvent:
    """输入事件"""
    timestamp: datetime
    keycode: int
    character: str
    app_name: str
    app_bundle_id: str
    modifiers: dict
    is_ime_input: bool = False


class TextFieldMonitor:
    """
    使用 Accessibility API 监听文本框内容变化
    直接获取最终输入的内容，而不是键盘事件
    """
    
    def __init__(self, callback: Callable[[str, str, str], None]):
        """
        callback: (new_text, app_name, bundle_id) -> None
        """
        self.callback = callback
        self._running = False
        self._thread = None
        self._system_wide = AXUIElementCreateSystemWide()
        
        # 状态追踪
        self._last_value = ""
        self._last_app = ""
        self._last_element_hash = None
        self._poll_interval = 0.2  # 200ms 轮询间隔
    
    def _get_active_app(self) -> tuple[str, str]:
        """获取当前活跃应用"""
        try:
            workspace = NSWorkspace.sharedWorkspace()
            app = workspace.frontmostApplication()
            if app:
                return (
                    app.localizedName() or "Unknown",
                    app.bundleIdentifier() or "unknown"
                )
        except:
            pass
        return ("Unknown", "unknown")
    
    def _get_focused_text_value(self) -> tuple[Optional[str], int]:
        """
        获取当前焦点文本字段的值
        返回: (值, 元素哈希)
        """
        try:
            # 获取焦点元素
            err, focused = AXUIElementCopyAttributeValue(
                self._system_wide,
                kAXFocusedUIElementAttribute,
                None
            )
            if err != 0 or focused is None:
                return None, 0
            
            # 获取元素角色，确保是可编辑的文本字段
            err, role = AXUIElementCopyAttributeValue(
                focused,
                kAXRoleAttribute,
                None
            )
            
            # 计算元素哈希（用于检测焦点切换）
            element_hash = hash(str(focused))
            
            # 获取文本值
            err, value = AXUIElementCopyAttributeValue(
                focused,
                kAXValueAttribute,
                None
            )
            
            if err == 0 and value is not None:
                return str(value), element_hash
                
        except Exception as e:
            pass
        
        return None, 0
    
    def _extract_new_content(self, old_value: str, new_value: str) -> str:
        """
        提取新增的内容
        简单策略：如果新值比旧值长，且旧值是新值的前缀，则返回差异部分
        """
        if not old_value:
            return new_value
        
        if not new_value:
            return ""
        
        # 检查是否是追加
        if new_value.startswith(old_value):
            return new_value[len(old_value):]
        
        # 检查是否是在中间插入或替换
        # 找到公共前缀
        common_prefix_len = 0
        for i in range(min(len(old_value), len(new_value))):
            if old_value[i] == new_value[i]:
                common_prefix_len = i + 1
            else:
                break
        
        # 如果有新增内容
        if len(new_value) > len(old_value):
            # 返回新增部分（简化处理）
            return new_value[common_prefix_len:]
        
        return ""
    
    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                app_name, bundle_id = self._get_active_app()
                value, element_hash = self._get_focused_text_value()
                
                # 检测应用或焦点元素切换
                if app_name != self._last_app or element_hash != self._last_element_hash:
                    self._last_app = app_name
                    self._last_element_hash = element_hash
                    self._last_value = value or ""
                    time.sleep(self._poll_interval)
                    continue
                
                # 检测内容变化
                if value is not None and value != self._last_value:
                    # 提取新增内容
                    new_content = self._extract_new_content(self._last_value, value)
                    
                    if new_content and self.callback:
                        self.callback(new_content, app_name, bundle_id)
                    
                    self._last_value = value
                
                time.sleep(self._poll_interval)
                
            except Exception as e:
                time.sleep(0.5)
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print("✅ 文本框监听已启动")
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        print("⏹️ 监听已停止")


class KeyboardListener:
    """
    输入监听器
    使用 Accessibility API 监听文本框内容变化
    """
    
    def __init__(self, callback: Callable[[KeyEvent], None]):
        self.callback = callback
        self._running = False
        self._monitor = TextFieldMonitor(self._on_text_change)
    
    def _on_text_change(self, new_text: str, app_name: str, bundle_id: str):
        """文本变化回调"""
        # 为新内容创建事件
        key_event = KeyEvent(
            timestamp=datetime.now(),
            keycode=-1,
            character=new_text,
            app_name=app_name,
            app_bundle_id=bundle_id,
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            is_ime_input=False,
        )
        
        if self.callback:
            self.callback(key_event)
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._monitor.start()
    
    def stop(self):
        if not self._running:
            return
        self._running = False
        self._monitor.stop()
    
    def is_running(self) -> bool:
        return self._running


def check_accessibility_permission() -> bool:
    """检查是否有辅助功能权限"""
    from ApplicationServices import AXIsProcessTrusted
    return AXIsProcessTrusted()


def request_accessibility_permission():
    """请求辅助功能权限"""
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
    print("📝 监听文本框最终内容（不是键盘事件）")
    print("   支持：中文、英文、粘贴、任何输入方式")
    print("-" * 50)
    
    last_app = [""]
    
    def on_input(event: KeyEvent):
        if last_app[0] != event.app_name:
            if last_app[0]:
                print()
            print(f"\n[{event.app_name}]", flush=True)
            last_app[0] = event.app_name
        
        text = event.character
        # 处理换行显示
        if '\n' in text:
            for line in text.split('\n'):
                if line:
                    print(f"  {line}")
        else:
            print(f"  {text}")
    
    listener = KeyboardListener(on_input)
    listener.start()
    
    print("\n按 Ctrl+C 停止监听...\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        print("\n已停止")
