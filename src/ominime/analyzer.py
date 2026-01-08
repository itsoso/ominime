"""
汇总分析模块

生成每日报告、应用统计和智能建议
"""

import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass

from .database import get_database, AppDailyStats, DailySummary
from .config import config


@dataclass
class DailyReport:
    """每日报告"""
    date: date
    total_chars: int
    total_apps: int
    total_sessions: int
    total_time_minutes: float
    app_stats: List[AppDailyStats]
    main_activities: List[str]
    summary: str
    suggestions: List[str]


class Analyzer:
    """
    分析器
    
    生成各种统计报告和智能建议
    """
    
    def __init__(self):
        self.db = get_database()
        self._openai_client = None
    
    def _get_openai_client(self):
        """懒加载 OpenAI 客户端"""
        if not config.ai_enabled:
            return None
        
        if self._openai_client is None and config.openai_api_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=config.openai_api_key)
            except ImportError:
                print("⚠️ 未安装 openai 包，AI 功能不可用")
                return None
            except Exception as e:
                print(f"⚠️ OpenAI 初始化失败: {e}")
                return None
        
        return self._openai_client
    
    def generate_daily_report(self, target_date: Optional[date] = None) -> DailyReport:
        """
        生成每日报告
        
        Args:
            target_date: 目标日期，默认今天
        
        Returns:
            DailyReport 对象
        """
        if target_date is None:
            target_date = date.today()
        
        # 获取应用统计
        app_stats = self.db.get_daily_stats(target_date)
        
        # 计算总计
        total_chars = sum(s.total_chars for s in app_stats)
        total_sessions = sum(s.session_count for s in app_stats)
        total_time_minutes = sum(s.total_time_minutes for s in app_stats)
        total_apps = len(app_stats)
        
        # 提取主线活动
        main_activities = self._extract_main_activities(app_stats)
        
        # 生成总结
        summary = self._generate_summary(app_stats, target_date)
        
        # 生成建议
        suggestions = self._generate_suggestions(app_stats, total_chars, total_time_minutes)
        
        return DailyReport(
            date=target_date,
            total_chars=total_chars,
            total_apps=total_apps,
            total_sessions=total_sessions,
            total_time_minutes=total_time_minutes,
            app_stats=app_stats,
            main_activities=main_activities,
            summary=summary,
            suggestions=suggestions,
        )
    
    def _extract_main_activities(self, app_stats: List[AppDailyStats]) -> List[str]:
        """从应用统计中提取主线活动"""
        activities = []
        
        # 按字符数排序
        sorted_stats = sorted(app_stats, key=lambda x: x.total_chars, reverse=True)
        
        for stat in sorted_stats[:5]:  # 取前5个应用
            if stat.total_chars < 10:
                continue
            
            # 根据应用类型推断活动
            activity = self._infer_activity(stat)
            if activity:
                activities.append(activity)
        
        return activities
    
    def _infer_activity(self, stat: AppDailyStats) -> Optional[str]:
        """根据应用统计推断活动"""
        app_name = stat.display_name.lower()
        chars = stat.total_chars
        
        # 编程类
        if any(x in app_name for x in ['cursor', 'vscode', 'code', 'intellij', 'pycharm', 'sublime']):
            return f"代码开发 ({chars:,} 字符)"
        
        # 沟通类
        if any(x in app_name for x in ['微信', 'wechat', 'qq', '飞书', '钉钉', 'slack', 'zoom']):
            return f"即时通讯 ({chars:,} 字符)"
        
        # 笔记类
        if any(x in app_name for x in ['obsidian', 'notion', '备忘录', 'notes', 'evernote']):
            return f"笔记写作 ({chars:,} 字符)"
        
        # 浏览器
        if any(x in app_name for x in ['safari', 'chrome', 'firefox', 'edge']):
            return f"网页浏览/搜索 ({chars:,} 字符)"
        
        # 办公
        if any(x in app_name for x in ['word', 'excel', 'powerpoint', 'pages', 'numbers']):
            return f"办公文档 ({chars:,} 字符)"
        
        # 终端
        if any(x in app_name for x in ['terminal', '终端', 'iterm']):
            return f"命令行操作 ({chars:,} 字符)"
        
        # 邮件
        if any(x in app_name for x in ['mail', '邮件', 'outlook', 'gmail']):
            return f"邮件处理 ({chars:,} 字符)"
        
        # 其他
        if chars > 50:
            return f"{stat.display_name} ({chars:,} 字符)"
        
        return None
    
    def _generate_summary(self, app_stats: List[AppDailyStats], target_date: date) -> str:
        """生成每日总结"""
        if not app_stats:
            return "今日暂无输入记录。"
        
        # 尝试使用 AI 生成总结
        client = self._get_openai_client()
        if client:
            return self._ai_generate_summary(app_stats, target_date)
        
        # 基础总结
        total_chars = sum(s.total_chars for s in app_stats)
        top_app = max(app_stats, key=lambda x: x.total_chars)
        
        summary_parts = []
        summary_parts.append(f"今日共输入 {total_chars:,} 个字符，涉及 {len(app_stats)} 个应用。")
        summary_parts.append(f"主要活动集中在 {top_app.display_name}，共 {top_app.total_chars:,} 个字符。")
        
        # 分析时间分布
        coding_apps = ['Cursor', 'VS Code', 'IntelliJ IDEA', 'Sublime Text']
        coding_chars = sum(s.total_chars for s in app_stats if s.display_name in coding_apps)
        
        comm_apps = ['微信', 'QQ', '飞书', '钉钉', 'Slack']
        comm_chars = sum(s.total_chars for s in app_stats if s.display_name in comm_apps)
        
        if coding_chars > total_chars * 0.5:
            summary_parts.append("今日主要精力投入在代码开发上。")
        elif comm_chars > total_chars * 0.3:
            summary_parts.append("今日沟通交流占用了较多时间。")
        
        return " ".join(summary_parts)
    
    def _ai_generate_summary(self, app_stats: List[AppDailyStats], target_date: date) -> str:
        """使用 AI 生成总结"""
        client = self._get_openai_client()
        if not client:
            return self._generate_summary(app_stats, target_date)
        
        # 准备数据
        stats_text = "\n".join([
            f"- {s.display_name}: {s.total_chars}字符, {s.session_count}个会话"
            for s in app_stats[:10]
        ])
        
        # 准备样本内容
        samples = []
        for s in app_stats[:5]:
            for content in s.sample_content[:2]:
                if content and len(content) > 10:
                    samples.append(f"[{s.display_name}] {content[:100]}...")
        
        samples_text = "\n".join(samples[:10])
        
        prompt = f"""请根据以下用户今日({target_date})的输入统计，生成一段简洁的中文总结（不超过100字）：

应用统计:
{stats_text}

输入样本:
{samples_text}

要求：
1. 概括今日主要活动
2. 语气友好、简洁
3. 不要列举数字，重在概括
"""
        
        try:
            response = client.chat.completions.create(
                model=config.openai_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"AI 总结生成失败: {e}")
            return self._generate_summary(app_stats, target_date)
    
    def _generate_suggestions(
        self, 
        app_stats: List[AppDailyStats], 
        total_chars: int,
        total_time_minutes: float
    ) -> List[str]:
        """生成建议"""
        suggestions = []
        
        if not app_stats:
            return ["开始记录你的输入，了解你的时间都花在哪里。"]
        
        # 分析各类应用占比
        coding_apps = ['Cursor', 'VS Code', 'IntelliJ IDEA', 'Sublime Text', 'PyCharm']
        comm_apps = ['微信', 'QQ', '飞书', '钉钉', 'Slack', 'Zoom']
        
        coding_chars = sum(s.total_chars for s in app_stats if s.display_name in coding_apps)
        comm_chars = sum(s.total_chars for s in app_stats if s.display_name in comm_apps)
        
        if total_chars > 0:
            coding_ratio = coding_chars / total_chars
            comm_ratio = comm_chars / total_chars
            
            # 编程相关建议
            if coding_ratio > 0.7:
                suggestions.append("💡 代码输入占比很高，记得适当休息眼睛和手腕")
            
            # 沟通相关建议
            if comm_ratio > 0.4:
                suggestions.append("💬 沟通占用时间较多，可考虑设置专门的消息处理时段")
            
            # 时间相关建议
            if total_time_minutes > 300:  # 超过5小时
                suggestions.append("⏰ 今日活跃时间较长，注意劳逸结合")
        
        # 多应用切换建议
        if len(app_stats) > 8:
            suggestions.append("🔄 今日使用了多个应用，频繁切换可能影响专注度")
        
        # AI 增强建议
        client = self._get_openai_client()
        if client:
            ai_suggestions = self._ai_generate_suggestions(app_stats, total_chars)
            suggestions.extend(ai_suggestions)
        
        return suggestions if suggestions else ["👍 继续保持，明天见！"]
    
    def _ai_generate_suggestions(self, app_stats: List[AppDailyStats], total_chars: int) -> List[str]:
        """使用 AI 生成个性化建议"""
        client = self._get_openai_client()
        if not client:
            return []
        
        stats_text = "\n".join([
            f"- {s.display_name}: {s.total_chars}字符"
            for s in app_stats[:10]
        ])
        
        prompt = f"""基于用户今日的应用使用统计，给出1-2条简短的效率或健康建议：

{stats_text}

总字符数: {total_chars}

要求：
1. 每条建议不超过30字
2. 以emoji开头
3. 具体、可执行
4. 语气友好
"""
        
        try:
            response = client.chat.completions.create(
                model=config.openai_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.8,
            )
            
            text = response.choices[0].message.content.strip()
            # 解析多行建议
            suggestions = [line.strip() for line in text.split('\n') if line.strip()]
            return suggestions[:2]
        except Exception as e:
            print(f"AI 建议生成失败: {e}")
            return []
    
    def format_report(self, report: DailyReport) -> str:
        """格式化报告为文本"""
        lines = []
        
        # 标题
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday = weekday_names[report.date.weekday()]
        lines.append(f"📅 {report.date.strftime('%Y-%m-%d')} {weekday} 输入汇总")
        lines.append("=" * 40)
        lines.append("")
        
        # 概览
        lines.append(f"📊 总计: {report.total_chars:,} 字符 | {report.total_apps} 应用 | {report.total_sessions} 会话")
        if report.total_time_minutes > 0:
            hours = int(report.total_time_minutes // 60)
            mins = int(report.total_time_minutes % 60)
            lines.append(f"⏱️  活跃时间: {hours}小时{mins}分钟")
        lines.append("")
        
        # 各应用统计
        if report.app_stats:
            lines.append("📱 应用分布:")
            lines.append("-" * 30)
            
            for stat in report.app_stats[:10]:
                # 计算占比
                ratio = stat.total_chars / report.total_chars * 100 if report.total_chars > 0 else 0
                bar_len = int(ratio / 5)  # 每5%一个块
                bar = "█" * bar_len + "░" * (20 - bar_len)
                
                lines.append(f"  {stat.display_name}")
                lines.append(f"    {bar} {stat.total_chars:,}字 ({ratio:.1f}%)")
            lines.append("")
        
        # 主线活动
        if report.main_activities:
            lines.append("🎯 今日主线活动:")
            for i, activity in enumerate(report.main_activities, 1):
                lines.append(f"  {i}. {activity}")
            lines.append("")
        
        # 总结
        lines.append("📝 总结:")
        lines.append(f"  {report.summary}")
        lines.append("")
        
        # 建议
        if report.suggestions:
            lines.append("💡 建议:")
            for suggestion in report.suggestions:
                lines.append(f"  {suggestion}")
        
        return "\n".join(lines)
    
    def get_weekly_trend(self) -> Dict:
        """获取周趋势数据"""
        days = self.db.get_recent_days_summary(7)
        
        return {
            "days": days,
            "total_chars": sum(d.get('total_chars', 0) for d in days),
            "avg_chars_per_day": sum(d.get('total_chars', 0) for d in days) / max(len(days), 1),
        }


# 全局分析器实例
_analyzer_instance: Optional[Analyzer] = None


def get_analyzer() -> Analyzer:
    """获取分析器单例"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = Analyzer()
    return _analyzer_instance


# 测试代码
if __name__ == "__main__":
    analyzer = get_analyzer()
    
    # 生成今日报告
    report = analyzer.generate_daily_report()
    
    # 打印格式化报告
    print(analyzer.format_report(report))

