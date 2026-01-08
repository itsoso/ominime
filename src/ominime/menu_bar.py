"""
Menu Bar 应用模块

在 macOS 状态栏显示应用图标，提供控制界面
"""

import rumps
from datetime import date
from typing import Optional

from .keyboard_listener import KeyboardListener, KeyEvent, check_accessibility_permission, request_accessibility_permission
from .app_tracker import AppTracker
from .database import get_database, InputRecord
from .analyzer import get_analyzer
from .config import config


class OmniMeApp(rumps.App):
    """
    OmniMe Menu Bar 应用
    
    显示在状态栏，提供：
    - 开始/停止记录
    - 查看今日统计
    - 查看详细报告
    - 设置
    """
    
    def __init__(self):
        super().__init__(
            name="OmniMe",
            title="⌨️",
            quit_button=None,  # 自定义退出按钮
        )
        
        self.listener: Optional[KeyboardListener] = None
        self.tracker = AppTracker()
        self.db = get_database()
        self.analyzer = get_analyzer()
        
        self._is_recording = False
        self._today_chars = 0
        
        # 构建菜单
        self._build_menu()
        
        # 设置定时器，每分钟更新统计
        self._stats_timer = rumps.Timer(self._update_stats, 60)
        self._stats_timer.start()
    
    def _build_menu(self):
        """构建菜单"""
        self.menu = [
            rumps.MenuItem("📊 今日统计", callback=self._show_today_stats),
            rumps.MenuItem("📝 查看报告", callback=self._show_report),
            None,  # 分隔线
            rumps.MenuItem("▶️ 开始记录", callback=self._toggle_recording),
            None,
            rumps.MenuItem("⚙️ 设置", callback=self._show_settings),
            rumps.MenuItem("❓ 关于", callback=self._show_about),
            None,
            rumps.MenuItem("🚪 退出", callback=self._quit),
        ]
    
    def _on_key_event(self, event: KeyEvent):
        """键盘事件回调"""
        # 忽略特殊键
        if event.character in ['esc', '←', '→', '↑', '↓', 'del']:
            return
        
        # 忽略带 Command 键的快捷键（如 Cmd+C）
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
        )
        
        if session:
            self._today_chars += 1
            
            # 当缓冲区达到一定长度时保存到数据库
            if len(session.buffer) >= 50:
                self._save_session(session)
                session.buffer = ""
        
        # 更新标题显示字符数
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
            self.title = "⌨️"
    
    def _update_stats(self, _):
        """定时更新统计"""
        if self._is_recording:
            # 从数据库获取今日总字符数
            self._today_chars = self.db.get_total_chars_today()
            self._update_title()
    
    def _toggle_recording(self, sender):
        """切换记录状态"""
        if not self._is_recording:
            self._start_recording(sender)
        else:
            self._stop_recording(sender)
    
    def _start_recording(self, sender):
        """开始记录"""
        # 检查权限
        if not check_accessibility_permission():
            rumps.alert(
                title="需要辅助功能权限",
                message="请在「系统偏好设置 → 隐私与安全性 → 辅助功能」中授予 OmniMe 权限，然后重试。",
                ok="打开设置"
            )
            request_accessibility_permission()
            return
        
        # 启动监听
        self.listener = KeyboardListener(self._on_key_event)
        self.listener.start()
        
        self._is_recording = True
        sender.title = "⏸️ 暂停记录"
        self._update_title()
        
        rumps.notification(
            title="OmniMe",
            subtitle="开始记录",
            message="键盘输入监听已启动"
        )
    
    def _stop_recording(self, sender):
        """停止记录"""
        if self.listener:
            # 保存当前会话
            self.tracker.flush_current_session()
            if self.tracker._current_session:
                self._save_session(self.tracker._current_session)
            
            self.listener.stop()
            self.listener = None
        
        self._is_recording = False
        sender.title = "▶️ 开始记录"
        self.title = "⌨️"
        
        rumps.notification(
            title="OmniMe",
            subtitle="已停止记录",
            message="键盘输入监听已暂停"
        )
    
    def _show_today_stats(self, _):
        """显示今日统计"""
        stats = self.db.get_daily_stats(date.today())
        
        if not stats:
            rumps.alert(
                title="📊 今日统计",
                message="今日暂无记录，开始记录后数据将在这里显示。"
            )
            return
        
        total_chars = sum(s.total_chars for s in stats)
        
        # 构建统计信息
        lines = [f"总输入: {total_chars:,} 字符\n"]
        lines.append("应用分布:")
        
        for stat in stats[:8]:
            ratio = stat.total_chars / total_chars * 100 if total_chars > 0 else 0
            lines.append(f"  • {stat.display_name}: {stat.total_chars:,} ({ratio:.1f}%)")
        
        rumps.alert(
            title="📊 今日统计",
            message="\n".join(lines)
        )
    
    def _show_report(self, _):
        """显示详细报告"""
        report = self.analyzer.generate_daily_report()
        formatted = self.analyzer.format_report(report)
        
        # rumps.alert 对长文本支持有限，使用简化版本
        lines = []
        lines.append(f"日期: {report.date}")
        lines.append(f"总字符: {report.total_chars:,}")
        lines.append(f"应用数: {report.total_apps}")
        lines.append("")
        
        if report.main_activities:
            lines.append("主线活动:")
            for act in report.main_activities[:3]:
                lines.append(f"  • {act}")
            lines.append("")
        
        lines.append("总结:")
        lines.append(report.summary[:200])
        
        if report.suggestions:
            lines.append("")
            lines.append("建议:")
            for sug in report.suggestions[:2]:
                lines.append(f"  {sug}")
        
        rumps.alert(
            title="📝 每日报告",
            message="\n".join(lines)
        )
    
    def _show_settings(self, _):
        """显示设置"""
        settings_info = f"""
数据存储位置:
{config.data_dir}

AI 总结: {'已启用' if config.ai_enabled else '未启用'}

会话超时: {config.session_timeout} 秒

要修改设置，请编辑:
{config.data_dir / 'config.json'}
"""
        rumps.alert(
            title="⚙️ 设置",
            message=settings_info
        )
    
    def _show_about(self, _):
        """显示关于信息"""
        about_text = """
OmniMe - 输入追踪系统 v0.1.0

记录你在不同应用中的每一次输入，
智能汇总分析你的一天。

功能:
• 全局键盘输入监听
• 按应用分类统计
• 每日报告生成
• AI 智能建议（可选）

所有数据仅存储在本地。
"""
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


def run_menu_bar_app():
    """运行 Menu Bar 应用"""
    app = OmniMeApp()
    app.run()


if __name__ == "__main__":
    run_menu_bar_app()

