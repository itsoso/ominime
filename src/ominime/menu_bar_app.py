"""
OmniMe Menu Bar 应用（完整版）

集成键盘监听、Web 服务和菜单栏控制
"""

import rumps
import threading
import webbrowser
import os
import sys
from datetime import date
from typing import Optional

from .keyboard_listener import KeyboardListener, KeyEvent, check_accessibility_permission, request_accessibility_permission
from .app_tracker import AppTracker
from .database import get_database, InputRecord
from .config import config


class OmniMeMenuBarApp(rumps.App):
    """
    OmniMe 完整版 Menu Bar 应用
    
    功能:
    - 键盘输入监听（自动启动）
    - Web 后台管理
    - 统计查看
    - 开机启动管理
    """
    
    def __init__(self):
        super().__init__(
            name="OmniMe",
            title="⌨️",
            quit_button=None,
        )
        
        self.listener: Optional[KeyboardListener] = None
        self.tracker = AppTracker()
        self.db = get_database()
        
        self._is_recording = False
        self._today_chars = 0
        self._web_server_thread: Optional[threading.Thread] = None
        self._web_server_running = False
        
        # 构建菜单
        self._build_menu()
        
        # 设置定时器
        self._stats_timer = rumps.Timer(self._update_stats, 60)
        self._stats_timer.start()
        
        # 自动启动监听
        self._auto_start_recording()
    
    def _build_menu(self):
        """构建菜单"""
        self.menu = [
            rumps.MenuItem("📊 今日统计", callback=self._show_today_stats),
            rumps.MenuItem("🌐 打开 Web 后台", callback=self._open_web),
            None,  # 分隔线
            rumps.MenuItem("▶️ 开始记录", callback=self._toggle_recording),
            None,
            rumps.MenuItem("⚙️ 设置", callback=self._show_settings),
            rumps.MenuItem("📂 打开数据目录", callback=self._open_data_dir),
            None,
            rumps.MenuItem("🔄 设为开机启动", callback=self._setup_launch_agent),
            rumps.MenuItem("❌ 取消开机启动", callback=self._remove_launch_agent),
            None,
            rumps.MenuItem("❓ 关于", callback=self._show_about),
            rumps.MenuItem("🚪 退出", callback=self._quit),
        ]
    
    def _auto_start_recording(self):
        """自动启动监听"""
        if check_accessibility_permission():
            self._start_recording_internal()
        else:
            rumps.notification(
                title="OmniMe",
                subtitle="需要授权",
                message="请点击菜单栏图标授予辅助功能权限"
            )
    
    def _on_key_event(self, event: KeyEvent):
        """键盘事件回调"""
        # 忽略特殊键
        if event.character in ['esc', '←', '→', '↑', '↓', 'del']:
            return
        
        # 忽略带 Command 键的快捷键
        if event.modifiers.get('cmd'):
            return
        
        # 忽略被屏蔽的应用
        if config.is_app_ignored(event.app_bundle_id):
            return
        
        # 记录输入
        session = self.tracker.record_input(
            event.character,
            event.app_name,
            event.app_bundle_id,
            is_ime_input=event.is_ime_input
        )
        
        if session:
            self._today_chars += 1
            
            # 保存到数据库（每10个字符或遇到换行时保存）
            char = event.character
            should_save = len(session.buffer) >= 10 or char == '\n'
            if should_save and session.buffer.strip():
                self._save_session(session)
                session.buffer = ""
        
        # 更新标题
        self._update_title()
    
    def _save_session(self, session):
        """保存会话到数据库"""
        if not session.buffer:
            return
        
        record = InputRecord(
            id=None,
            timestamp=session.last_activity,
            app_name=session.app_name,
            app_bundle_id=session.app_bundle_id,
            display_name=config.get_app_display_name(session.app_bundle_id, session.app_name),
            content=session.buffer,
            char_count=len(session.buffer),
            session_id=session.session_id,
            duration_seconds=(session.last_activity - session.start_time).total_seconds(),
        )
        
        try:
            self.db.save_input_record(record)
        except Exception as e:
            print(f"保存记录失败: {e}")
    
    def _update_title(self):
        """更新状态栏标题"""
        if self._is_recording:
            if self._today_chars > 1000:
                self.title = f"⌨️ {self._today_chars // 1000}k"
            else:
                self.title = f"⌨️ {self._today_chars}"
        else:
            self.title = "⌨️ ⏸"
    
    def _update_stats(self, _):
        """定时更新统计"""
        if self._is_recording:
            self._today_chars = self.db.get_total_chars_today()
            self._update_title()
    
    def _toggle_recording(self, sender):
        """切换记录状态"""
        if not self._is_recording:
            self._start_recording(sender)
        else:
            self._stop_recording(sender)
    
    def _start_recording_internal(self):
        """内部启动记录（不更新菜单）"""
        self.listener = KeyboardListener(self._on_key_event)
        self.listener.start()
        self._is_recording = True
        self._today_chars = self.db.get_total_chars_today()
        self._update_title()
    
    def _start_recording(self, sender):
        """开始记录"""
        if not check_accessibility_permission():
            result = rumps.alert(
                title="需要辅助功能权限",
                message="请在「系统偏好设置 → 隐私与安全性 → 辅助功能」中授予 OmniMe 权限，然后重试。",
                ok="打开设置",
                cancel="取消"
            )
            if result == 1:
                request_accessibility_permission()
            return
        
        self._start_recording_internal()
        sender.title = "⏸️ 暂停记录"
        
        rumps.notification(
            title="OmniMe",
            subtitle="开始记录",
            message="键盘输入监听已启动"
        )
    
    def _stop_recording(self, sender):
        """停止记录"""
        if self.listener:
            self.tracker.flush_current_session()
            if self.tracker._current_session:
                self._save_session(self.tracker._current_session)
            
            self.listener.stop()
            self.listener = None
        
        self._is_recording = False
        sender.title = "▶️ 开始记录"
        self.title = "⌨️ ⏸"
        
        rumps.notification(
            title="OmniMe",
            subtitle="已停止记录",
            message="键盘输入监听已暂停"
        )
    
    def _open_web(self, _):
        """打开 Web 后台"""
        # 启动 Web 服务器（如果未运行）
        if not self._web_server_running:
            self._start_web_server()
        
        # 打开浏览器
        webbrowser.open("http://127.0.0.1:8080")
    
    def _start_web_server(self):
        """启动 Web 服务器"""
        if self._web_server_running:
            return
        
        def run_server():
            try:
                from .web.server import run_server as start_server
                self._web_server_running = True
                start_server(host="127.0.0.1", port=8080, reload=False)
            except Exception as e:
                print(f"Web 服务器错误: {e}")
                self._web_server_running = False
        
        self._web_server_thread = threading.Thread(target=run_server, daemon=True)
        self._web_server_thread.start()
        
        rumps.notification(
            title="OmniMe",
            subtitle="Web 服务已启动",
            message="访问 http://127.0.0.1:8080"
        )
    
    def _show_today_stats(self, _):
        """显示今日统计"""
        stats = self.db.get_daily_stats(date.today())
        
        if not stats:
            rumps.alert(
                title="📊 今日统计",
                message="今日暂无记录，开始使用后数据将在这里显示。"
            )
            return
        
        total_chars = sum(s.total_chars for s in stats)
        
        lines = [f"总输入: {total_chars:,} 字符\n"]
        lines.append("应用分布:")
        
        for stat in stats[:8]:
            ratio = stat.total_chars / total_chars * 100 if total_chars > 0 else 0
            lines.append(f"  • {stat.display_name}: {stat.total_chars:,} ({ratio:.1f}%)")
        
        rumps.alert(
            title="📊 今日统计",
            message="\n".join(lines)
        )
    
    def _open_data_dir(self, _):
        """打开数据目录"""
        os.system(f'open "{config.data_dir}"')
    
    def _show_settings(self, _):
        """显示设置"""
        settings_info = f"""数据存储位置:
{config.data_dir}

数据库位置:
{config.db_path}

会话超时: {config.session_timeout} 秒

要修改设置，请编辑:
{config.data_dir / 'config.json'}"""
        
        rumps.alert(
            title="⚙️ 设置",
            message=settings_info
        )
    
    def _setup_launch_agent(self, _):
        """设置开机启动"""
        import subprocess
        
        # 获取应用路径
        if getattr(sys, 'frozen', False):
            # 打包后的应用
            app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
        else:
            # 开发模式，使用 ominime 命令
            app_path = "ominime"
        
        plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ominime.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{config.data_dir}/ominime.log</string>
    <key>StandardErrorPath</key>
    <string>{config.data_dir}/ominime.error.log</string>
</dict>
</plist>'''
        
        # 写入 LaunchAgent 文件
        launch_agent_dir = os.path.expanduser("~/Library/LaunchAgents")
        os.makedirs(launch_agent_dir, exist_ok=True)
        
        plist_path = os.path.join(launch_agent_dir, "com.ominime.app.plist")
        
        try:
            with open(plist_path, 'w') as f:
                f.write(plist_content)
            
            # 加载 LaunchAgent
            subprocess.run(['launchctl', 'unload', plist_path], capture_output=True)
            subprocess.run(['launchctl', 'load', plist_path], capture_output=True)
            
            rumps.alert(
                title="✅ 设置成功",
                message="OmniMe 已设为开机启动。\n\n下次开机时将自动运行。"
            )
        except Exception as e:
            rumps.alert(
                title="❌ 设置失败",
                message=f"无法设置开机启动: {e}"
            )
    
    def _remove_launch_agent(self, _):
        """取消开机启动"""
        import subprocess
        
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.ominime.app.plist")
        
        try:
            if os.path.exists(plist_path):
                subprocess.run(['launchctl', 'unload', plist_path], capture_output=True)
                os.remove(plist_path)
            
            rumps.alert(
                title="✅ 取消成功",
                message="OmniMe 开机启动已取消。"
            )
        except Exception as e:
            rumps.alert(
                title="❌ 取消失败",
                message=f"无法取消开机启动: {e}"
            )
    
    def _show_about(self, _):
        """显示关于信息"""
        about_text = """OmniMe - 输入追踪系统 v0.1.0

记录你在不同应用中的每一次输入，
智能汇总分析你的一天。

功能:
• 全局键盘输入监听
• 按应用分类统计
• Web 后台管理
• 开机自动启动

所有数据仅存储在本地。"""
        
        rumps.alert(
            title="❓ 关于 OmniMe",
            message=about_text
        )
    
    def _quit(self, _):
        """退出应用"""
        # 停止记录
        if self.listener:
            self.tracker.flush_current_session()
            if self.tracker._current_session:
                self._save_session(self.tracker._current_session)
            self.listener.stop()
        
        # 停止定时器
        self._stats_timer.stop()
        
        rumps.quit_application()


def run_app():
    """运行应用"""
    app = OmniMeMenuBarApp()
    app.run()


if __name__ == "__main__":
    run_app()
