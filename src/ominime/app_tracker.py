"""
应用追踪模块

追踪当前活跃的应用程序，管理输入会话
"""

import time
import uuid
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification
from Foundation import NSNotificationCenter

from .config import config


@dataclass
class InputSession:
    """输入会话"""
    session_id: str
    app_name: str
    app_bundle_id: str
    start_time: datetime
    last_activity: datetime
    buffer: str = ""  # 当前输入缓冲区
    char_count: int = 0
    
    def append(self, char: str):
        """添加字符到缓冲区"""
        if char == '\b':  # Backspace
            if self.buffer:
                self.buffer = self.buffer[:-1]
        else:
            self.buffer += char
            self.char_count += 1
        self.last_activity = datetime.now()
    
    def is_expired(self, timeout_seconds: int) -> bool:
        """检查会话是否已过期"""
        elapsed = (datetime.now() - self.last_activity).total_seconds()
        return elapsed > timeout_seconds


@dataclass
class AppStats:
    """应用统计信息"""
    app_name: str
    app_bundle_id: str
    display_name: str
    total_chars: int = 0
    session_count: int = 0
    total_time_seconds: float = 0
    content_samples: List[str] = field(default_factory=list)
    
    def add_content(self, content: str, max_samples: int = 10):
        """添加内容样本"""
        if content and len(content) > 5:
            self.content_samples.append(content)
            if len(self.content_samples) > max_samples:
                self.content_samples.pop(0)


class AppTracker:
    """
    应用追踪器
    
    管理当前活跃应用和输入会话
    """
    
    def __init__(self):
        self._current_app: Optional[str] = None
        self._current_bundle_id: Optional[str] = None
        self._current_session: Optional[InputSession] = None
        self._sessions: Dict[str, InputSession] = {}  # session_id -> session
        self._completed_sessions: List[InputSession] = []
        self._app_stats: Dict[str, AppStats] = {}  # bundle_id -> stats
        
        # 初始化当前应用
        self._update_current_app()
    
    def _update_current_app(self) -> tuple[str, str]:
        """更新当前活跃应用"""
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        
        if active_app:
            self._current_app = active_app.localizedName() or "Unknown"
            self._current_bundle_id = active_app.bundleIdentifier() or "unknown"
        else:
            self._current_app = "Unknown"
            self._current_bundle_id = "unknown"
        
        return (self._current_app, self._current_bundle_id)
    
    def get_current_app(self) -> tuple[str, str]:
        """获取当前活跃的应用"""
        return (self._current_app, self._current_bundle_id)
    
    def get_display_name(self, bundle_id: str, app_name: str) -> str:
        """获取应用的显示名称"""
        return config.get_app_display_name(bundle_id, app_name)
    
    def is_app_ignored(self, bundle_id: str) -> bool:
        """检查应用是否被忽略"""
        return config.is_app_ignored(bundle_id)
    
    def get_or_create_session(self, app_name: str, bundle_id: str) -> InputSession:
        """获取或创建输入会话"""
        # 检查当前会话是否有效
        if self._current_session:
            # 如果应用相同且未过期，继续使用
            if (self._current_session.app_bundle_id == bundle_id and 
                not self._current_session.is_expired(config.session_timeout)):
                return self._current_session
            else:
                # 完成当前会话
                self._complete_session(self._current_session)
        
        # 创建新会话
        session = InputSession(
            session_id=str(uuid.uuid4()),
            app_name=app_name,
            app_bundle_id=bundle_id,
            start_time=datetime.now(),
            last_activity=datetime.now(),
        )
        self._current_session = session
        self._sessions[session.session_id] = session
        
        return session
    
    def _complete_session(self, session: InputSession):
        """完成一个会话"""
        if not session:
            return
        
        # 记录到完成会话列表
        self._completed_sessions.append(session)
        
        # 更新应用统计
        bundle_id = session.app_bundle_id
        if bundle_id not in self._app_stats:
            self._app_stats[bundle_id] = AppStats(
                app_name=session.app_name,
                app_bundle_id=bundle_id,
                display_name=self.get_display_name(bundle_id, session.app_name),
            )
        
        stats = self._app_stats[bundle_id]
        stats.total_chars += session.char_count
        stats.session_count += 1
        stats.total_time_seconds += (session.last_activity - session.start_time).total_seconds()
        stats.add_content(session.buffer)
    
    def record_input(self, char: str, app_name: str, bundle_id: str) -> InputSession:
        """记录一次输入"""
        if self.is_app_ignored(bundle_id):
            return None
        
        session = self.get_or_create_session(app_name, bundle_id)
        session.append(char)
        
        return session
    
    def flush_current_session(self):
        """强制完成当前会话"""
        if self._current_session:
            self._complete_session(self._current_session)
            self._current_session = None
    
    def get_app_stats(self) -> Dict[str, AppStats]:
        """获取所有应用统计"""
        # 先完成当前会话的统计
        if self._current_session:
            bundle_id = self._current_session.app_bundle_id
            if bundle_id not in self._app_stats:
                self._app_stats[bundle_id] = AppStats(
                    app_name=self._current_session.app_name,
                    app_bundle_id=bundle_id,
                    display_name=self.get_display_name(bundle_id, self._current_session.app_name),
                )
            
            # 临时更新统计（不完成会话）
            stats = self._app_stats[bundle_id]
            current_chars = self._current_session.char_count
            # 这里不累加，只是返回当前状态
        
        return self._app_stats
    
    def get_completed_sessions(self) -> List[InputSession]:
        """获取已完成的会话列表"""
        return self._completed_sessions.copy()
    
    def clear_stats(self):
        """清除所有统计数据"""
        self._sessions.clear()
        self._completed_sessions.clear()
        self._app_stats.clear()
        self._current_session = None


class AppMonitor:
    """
    应用切换监控器
    
    监听应用切换事件
    """
    
    def __init__(self, on_app_change=None):
        self.on_app_change = on_app_change
        self._observer = None
    
    def start(self):
        """开始监控"""
        center = NSNotificationCenter.defaultCenter()
        self._observer = center.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidActivateApplicationNotification,
            NSWorkspace.sharedWorkspace().notificationCenter(),
            None,
            self._on_notification
        )
    
    def _on_notification(self, notification):
        """应用切换通知回调"""
        if self.on_app_change:
            app = notification.userInfo()["NSWorkspaceApplicationKey"]
            self.on_app_change(
                app.localizedName(),
                app.bundleIdentifier()
            )
    
    def stop(self):
        """停止监控"""
        if self._observer:
            NSNotificationCenter.defaultCenter().removeObserver_(self._observer)
            self._observer = None


# 测试代码
if __name__ == "__main__":
    tracker = AppTracker()
    
    print("当前应用:", tracker.get_current_app())
    
    # 模拟一些输入
    tracker.record_input("H", "Cursor", "com.todesktop.230313mzl4w4u92")
    tracker.record_input("e", "Cursor", "com.todesktop.230313mzl4w4u92")
    tracker.record_input("l", "Cursor", "com.todesktop.230313mzl4w4u92")
    tracker.record_input("l", "Cursor", "com.todesktop.230313mzl4w4u92")
    tracker.record_input("o", "Cursor", "com.todesktop.230313mzl4w4u92")
    
    print("当前会话:", tracker._current_session)
    print("应用统计:", tracker.get_app_stats())

