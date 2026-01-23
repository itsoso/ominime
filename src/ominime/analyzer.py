"""
汇总分析模块

生成每日报告、应用统计和智能建议
"""

import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from .database import get_database, AppDailyStats, DailySummary, InputRecord
from .config import config


@dataclass
class WorkPathSegment:
    """工作路径片段"""
    start_time: datetime
    end_time: datetime
    app_name: str
    display_name: str
    char_count: int
    duration_minutes: float
    content_preview: str


@dataclass
class WorkPathAnalysis:
    """工作路径分析"""
    segments: List[WorkPathSegment]
    total_segments: int
    app_switches: int
    peak_hours: List[Tuple[int, int]]  # [(hour, char_count), ...]
    focus_periods: List[Tuple[datetime, datetime, str]]  # [(start, end, app), ...]
    work_pattern: str  # "集中型" / "分散型" / "混合型"
    efficiency_score: float  # 0-100
    ai_analysis: Optional[str] = None  # AI 生成的工作路径分析


@dataclass
class ThemeAnalysis:
    """主题分析"""
    themes: List[str]  # 今日主要主题列表
    work_focus: str  # 工作重点回顾
    current_interests: List[str]  # 当前关注的内容
    insights: List[str]  # 洞察和启发
    detailed_summary: str  # 详细总结


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
    work_path: Optional[WorkPathAnalysis] = None
    ai_work_analysis: Optional[str] = None  # AI 生成的工作分析
    theme_analysis: Optional[ThemeAnalysis] = None  # 主题深度分析


class Analyzer:
    """
    分析器
    
    生成各种统计报告和智能建议
    """
    
    def __init__(self):
        self.db = get_database()
        self._llm_backend = None
    
    def _get_llm_backend(self):
        """懒加载 LLM 后端"""
        if not config.ai_enabled:
            return None
        
        if self._llm_backend is None:
            try:
                from .llm_backend import get_llm_backend
                self._llm_backend = get_llm_backend()
                if self._llm_backend is None:
                    print("⚠️ 未配置 LLM 后端，AI 功能不可用")
                    return None
            except Exception as e:
                print(f"⚠️ LLM 后端初始化失败: {e}")
                return None
        
        return self._llm_backend
    
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
        
        # 工作路径分析
        work_path = self._analyze_work_path(target_date)
        
        # 生成建议（包含工作路径信息）
        suggestions = self._generate_suggestions(app_stats, total_chars, total_time_minutes, work_path)
        
        # AI 工作分析
        ai_work_analysis = None
        if config.ai_enabled and work_path:
            ai_work_analysis = self._ai_analyze_work_path(work_path, app_stats, target_date)
        
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
            work_path=work_path,
            ai_work_analysis=ai_work_analysis,
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
        backend = self._get_llm_backend()
        if backend:
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
        backend = self._get_llm_backend()
        if not backend:
            return self._generate_summary(app_stats, target_date)
        
        # 准备数据
        stats_text = "\n".join([
            f"- {s.display_name}: {s.total_chars}字符, {s.session_count}个会话"
            for s in app_stats[:10]
        ])
        
        # 准备样本内容（更丰富的内容用于分析）
        samples = []
        for s in app_stats[:5]:
            for content in s.sample_content[:3]:
                if content and len(content) > 20:
                    samples.append(f"[{s.display_name}] {content[:150]}...")
        
        samples_text = "\n".join(samples[:15])
        
        total_chars = sum(s.total_chars for s in app_stats)
        
        prompt = f"""请根据以下用户{target_date}的输入统计和内容样本，生成一段150-200字的中文总结：

应用统计:
{stats_text}

总字符数: {total_chars:,}

输入内容样本:
{samples_text}

要求：
1. 概括今日主要工作内容和活动类型
2. 识别工作重点和主要任务
3. 分析工作节奏和效率特点
4. 语气专业但友好
5. 避免简单列举数字，重在洞察和分析
"""
        
        try:
            from .llm_backend import LLMMessage
            
            response = backend.chat(
                messages=[
                    LLMMessage(role="system", content="你是一个专业的工作效率分析师，擅长从数据中提取洞察。"),
                    LLMMessage(role="user", content=prompt)
                ],
                max_tokens=400,
                temperature=0.7,
            )
            return response.content.strip()
        except Exception as e:
            print(f"AI 总结生成失败: {e}")
            return self._generate_summary(app_stats, target_date)
    
    def _generate_suggestions(
        self, 
        app_stats: List[AppDailyStats], 
        total_chars: int,
        total_time_minutes: float,
        work_path: Optional[WorkPathAnalysis] = None
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
        
        # 工作路径相关建议
        if work_path:
            if work_path.work_pattern == "分散型":
                suggestions.append("🔄 工作模式较为分散，建议设置专注时段减少应用切换")
            elif work_path.app_switches > 50:
                suggestions.append("🔄 应用切换频繁，可能影响深度工作，建议批量处理任务")
            
            if work_path.efficiency_score < 60:
                suggestions.append("📈 效率分数较低，建议优化工作节奏，增加专注时段")
            elif len(work_path.focus_periods) < 2:
                suggestions.append("🎯 深度工作时间较少，建议安排2-3个专注时段")
        
        # 多应用切换建议
        if len(app_stats) > 8:
            suggestions.append("🔄 今日使用了多个应用，频繁切换可能影响专注度")
        
        # AI 增强建议
        backend = self._get_llm_backend()
        if backend:
            ai_suggestions = self._ai_generate_suggestions(app_stats, total_chars, work_path)
            suggestions.extend(ai_suggestions)
        
        return suggestions if suggestions else ["👍 继续保持，明天见！"]
    
    def _ai_generate_suggestions(
        self, 
        app_stats: List[AppDailyStats], 
        total_chars: int,
        work_path: Optional[WorkPathAnalysis] = None
    ) -> List[str]:
        """使用 AI 生成个性化建议"""
        backend = self._get_llm_backend()
        if not backend:
            return []
        
        stats_text = "\n".join([
            f"- {s.display_name}: {s.total_chars}字符, {s.session_count}个会话"
            for s in app_stats[:10]
        ])
        
        # 添加工作路径信息
        work_path_info = ""
        if work_path:
            work_path_info = f"""
工作模式: {work_path.work_pattern}
效率分数: {work_path.efficiency_score:.1f}/100
应用切换次数: {work_path.app_switches}
专注时段数: {len(work_path.focus_periods)}
峰值时段: {', '.join([f'{h}点' for h, _ in work_path.peak_hours[:3]])}
"""
        
        prompt = f"""基于用户今日的应用使用统计和工作路径分析，给出3-5条具体、可执行的效率或健康建议：

应用统计:
{stats_text}

总字符数: {total_chars}
{work_path_info}

要求：
1. 每条建议30-50字，具体可执行
2. 以emoji开头（💡 ⏰ 🎯 🔄 💪 等）
3. 基于数据给出针对性建议
4. 语气友好、鼓励性
5. 涵盖效率、健康、专注度等方面
"""
        
        try:
            from .llm_backend import LLMMessage
            
            response = backend.chat(
                messages=[
                    LLMMessage(role="system", content="你是一个专业的工作效率顾问，擅长给出具体可执行的改进建议。"),
                    LLMMessage(role="user", content=prompt)
                ],
                max_tokens=300,
                temperature=0.8,
            )
            
            text = response.content.strip()
            # 解析多行建议
            suggestions = []
            for line in text.split('\n'):
                line = line.strip()
                if line and (line.startswith('💡') or line.startswith('⏰') or 
                           line.startswith('🎯') or line.startswith('🔄') or 
                           line.startswith('💪') or line.startswith('📝') or
                           line.startswith('✨') or line.startswith('🌟')):
                    suggestions.append(line)
            
            return suggestions[:5] if suggestions else []
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
        
        # 工作路径分析
        if report.work_path:
            lines.append("🛤️  工作路径分析:")
            lines.append(f"  工作模式: {report.work_path.work_pattern}")
            lines.append(f"  效率分数: {report.work_path.efficiency_score:.1f}/100")
            lines.append(f"  应用切换: {report.work_path.app_switches} 次")
            lines.append(f"  专注时段: {len(report.work_path.focus_periods)} 个")
            
            if report.work_path.peak_hours:
                peak_str = ", ".join([f"{h}点({c:,}字符)" for h, c in report.work_path.peak_hours[:3]])
                lines.append(f"  峰值时段: {peak_str}")
            
            if report.work_path.focus_periods:
                lines.append("  深度工作时段:")
                for start, end, app in report.work_path.focus_periods[:3]:
                    duration = (end - start).total_seconds() / 60
                    lines.append(f"    • {start.strftime('%H:%M')}-{end.strftime('%H:%M')} {app} ({duration:.0f}分钟)")
            lines.append("")
        
        # AI 工作分析
        if report.ai_work_analysis:
            lines.append("🤖 AI 深度分析:")
            # 按段落格式化
            paragraphs = report.ai_work_analysis.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    lines.append(f"  {para.strip()}")
            lines.append("")
        
        # 主题深度分析
        if report.theme_analysis:
            theme = report.theme_analysis
            
            # 今日主题
            if theme.themes:
                lines.append("🎯 今日主题:")
                for i, t in enumerate(theme.themes, 1):
                    lines.append(f"  {i}. {t}")
                lines.append("")
            
            # 工作重点回顾
            if theme.work_focus:
                lines.append("📋 工作重点回顾:")
                lines.append(f"  {theme.work_focus}")
                lines.append("")
            
            # 当前关注
            if theme.current_interests:
                lines.append("🔍 当前关注:")
                for interest in theme.current_interests:
                    lines.append(f"  • {interest}")
                lines.append("")
            
            # 洞察与启发
            if theme.insights:
                lines.append("💡 洞察与启发:")
                for insight in theme.insights:
                    lines.append(f"  ✨ {insight}")
                lines.append("")
            
            # 详细总结
            if theme.detailed_summary:
                lines.append("📝 深度总结:")
                lines.append(f"  {theme.detailed_summary}")
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
    
    def _analyze_work_path(self, target_date: date) -> Optional[WorkPathAnalysis]:
        """分析工作路径"""
        records = self.db.get_records_by_date(target_date)
        
        if not records:
            return None
        
        # 按时间排序
        records.sort(key=lambda x: x.timestamp)
        
        # 构建工作路径片段
        segments = []
        current_segment = None
        
        for record in records:
            if current_segment is None or \
               current_segment.display_name != record.display_name or \
               (record.timestamp - current_segment.end_time).total_seconds() > 300:  # 5分钟间隔视为新片段
                
                # 保存上一个片段
                if current_segment:
                    segments.append(current_segment)
                
                # 创建新片段
                current_segment = WorkPathSegment(
                    start_time=record.timestamp,
                    end_time=record.timestamp,
                    app_name=record.app_name,
                    display_name=record.display_name,
                    char_count=record.char_count,
                    duration_minutes=0,
                    content_preview=record.content[:50] if record.content else ""
                )
            else:
                # 更新当前片段
                current_segment.end_time = record.timestamp
                current_segment.char_count += record.char_count
                if record.content and len(record.content) > len(current_segment.content_preview):
                    current_segment.content_preview = record.content[:50]
        
        # 添加最后一个片段
        if current_segment:
            segments.append(current_segment)
        
        # 计算每个片段的持续时间
        for segment in segments:
            duration_seconds = (segment.end_time - segment.start_time).total_seconds()
            segment.duration_minutes = duration_seconds / 60.0
        
        # 计算应用切换次数
        app_switches = 0
        prev_app = None
        for segment in segments:
            if prev_app and prev_app != segment.display_name:
                app_switches += 1
            prev_app = segment.display_name
        
        # 分析峰值时段（按小时统计）
        hour_chars = {}
        for record in records:
            hour = record.timestamp.hour
            hour_chars[hour] = hour_chars.get(hour, 0) + record.char_count
        
        peak_hours = sorted(hour_chars.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # 识别专注时段（连续30分钟以上在同一应用且输入量较大）
        focus_periods = []
        for segment in segments:
            if segment.duration_minutes >= 30 and segment.char_count >= 100:
                focus_periods.append((
                    segment.start_time,
                    segment.end_time,
                    segment.display_name
                ))
        
        # 判断工作模式
        work_pattern = self._identify_work_pattern(segments, app_switches)
        
        # 计算效率分数（基于专注时段、应用切换频率等）
        efficiency_score = self._calculate_efficiency_score(
            segments, app_switches, total_chars=sum(s.char_count for s in segments)
        )
        
        return WorkPathAnalysis(
            segments=segments,
            total_segments=len(segments),
            app_switches=app_switches,
            peak_hours=peak_hours,
            focus_periods=focus_periods,
            work_pattern=work_pattern,
            efficiency_score=efficiency_score,
        )
    
    def _identify_work_pattern(self, segments: List[WorkPathSegment], app_switches: int) -> str:
        """识别工作模式"""
        if not segments:
            return "未知"
        
        # 计算平均片段时长
        avg_duration = sum(s.duration_minutes for s in segments) / len(segments)
        
        # 计算切换频率
        switch_rate = app_switches / max(len(segments), 1)
        
        # 判断模式
        if avg_duration >= 60 and switch_rate < 0.3:
            return "集中型"  # 长时间专注，切换少
        elif avg_duration < 15 and switch_rate > 0.7:
            return "分散型"  # 短时间片段，频繁切换
        else:
            return "混合型"  # 介于两者之间
    
    def _calculate_efficiency_score(self, segments: List[WorkPathSegment], app_switches: int, total_chars: int) -> float:
        """计算效率分数（0-100）"""
        if not segments:
            return 0.0
        
        score = 100.0
        
        # 专注时段加分
        focus_count = sum(1 for s in segments if s.duration_minutes >= 30 and s.char_count >= 100)
        score += min(focus_count * 5, 20)  # 最多加20分
        
        # 过度切换扣分
        switch_rate = app_switches / max(len(segments), 1)
        if switch_rate > 0.8:
            score -= (switch_rate - 0.8) * 50  # 切换率超过0.8时扣分
        
        # 输入量加分
        if total_chars > 5000:
            score += min((total_chars - 5000) / 1000 * 2, 10)  # 每1000字符加2分，最多10分
        
        return max(0.0, min(100.0, score))
    
    def _ai_analyze_work_path(
        self, 
        work_path: WorkPathAnalysis, 
        app_stats: List[AppDailyStats],
        target_date: date
    ) -> Optional[str]:
        """使用 AI 分析工作路径"""
        backend = self._get_llm_backend()
        if not backend:
            return None
        
        # 准备时间线数据
        timeline = []
        for segment in work_path.segments[:20]:  # 限制前20个片段
            timeline.append(
                f"{segment.start_time.strftime('%H:%M')}-{segment.end_time.strftime('%H:%M')} "
                f"[{segment.display_name}] {segment.char_count}字符"
            )
        
        # 准备应用统计
        app_summary = "\n".join([
            f"- {s.display_name}: {s.total_chars}字符, {s.session_count}个会话"
            for s in app_stats[:10]
        ])
        
        # 准备峰值时段
        peak_info = ", ".join([f"{h}点({c}字符)" for h, c in work_path.peak_hours[:3]])
        
        # 准备专注时段
        focus_info = []
        for start, end, app in work_path.focus_periods[:5]:
            duration = (end - start).total_seconds() / 60
            focus_info.append(f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')} {app} ({duration:.0f}分钟)")
        
        prompt = f"""请分析用户{target_date}的工作路径，给出深度的工作模式分析和建议。

工作路径时间线:
{chr(10).join(timeline)}

应用统计:
{app_summary}

峰值时段: {peak_info}
工作模式: {work_path.work_pattern}
效率分数: {work_path.efficiency_score:.1f}/100
应用切换次数: {work_path.app_switches}
专注时段数: {len(work_path.focus_periods)}

请从以下角度分析（每个角度2-3句话）：
1. 工作节奏分析：识别工作的高效时段和低效时段
2. 应用使用模式：分析应用切换是否合理，是否存在注意力分散
3. 专注度评估：评估深度工作时间占比
4. 效率优化建议：基于数据给出3-5条具体可执行的改进建议

要求：
- 分析要具体、有数据支撑
- 建议要可执行、有针对性
- 语气专业但友好
- 总字数控制在300-400字
"""
        
        try:
            from .llm_backend import LLMMessage
            
            response = backend.chat(
                messages=[
                    LLMMessage(role="system", content="你是一个专业的工作效率分析专家，擅长分析工作模式并提供优化建议。"),
                    LLMMessage(role="user", content=prompt)
                ],
                max_tokens=800,
                temperature=0.7,
            )
            return response.content.strip()
        except Exception as e:
            print(f"AI 工作路径分析失败: {e}")
            return None
    
    def generate_theme_analysis(self, target_date: Optional[date] = None) -> Optional[ThemeAnalysis]:
        """
        生成深度主题分析
        
        获取用户全部输入内容，分析形成主题总结、工作重点、关注内容和洞察启发
        
        Args:
            target_date: 目标日期，默认今天
        
        Returns:
            ThemeAnalysis 对象
        """
        if target_date is None:
            target_date = date.today()
        
        backend = self._get_llm_backend()
        if not backend:
            return None
        
        # 获取当天全部输入记录
        records = self.db.get_records_by_date(target_date)
        
        if not records:
            return None
        
        # 收集全部内容，按应用分组
        app_contents: Dict[str, List[str]] = {}
        for record in records:
            app_name = record.display_name or record.app_name
            if app_name not in app_contents:
                app_contents[app_name] = []
            if record.content and record.content.strip():
                app_contents[app_name].append(record.content.strip())
        
        # 构建内容摘要（限制总长度避免超出 token 限制）
        content_summary = []
        total_length = 0
        max_length = 12000  # 限制总内容长度
        
        for app_name, contents in app_contents.items():
            if total_length >= max_length:
                break
            
            app_text = f"\n【{app_name}】\n"
            for content in contents:
                if total_length + len(content) > max_length:
                    break
                # 过滤掉太短的内容
                if len(content) >= 5:
                    app_text += f"- {content}\n"
                    total_length += len(content) + 3
            
            if len(app_text) > len(f"\n【{app_name}】\n"):
                content_summary.append(app_text)
        
        full_content = "\n".join(content_summary)
        
        if not full_content.strip():
            return None
        
        # 获取应用统计
        app_stats = self.db.get_daily_stats(target_date)
        stats_text = "\n".join([
            f"- {s.display_name}: {s.total_chars}字符"
            for s in app_stats[:10]
        ])
        
        prompt = f"""请深度分析用户{target_date}的全部输入内容，生成综合性的工作日报分析。

用户今日应用统计:
{stats_text}

用户今日全部输入内容:
{full_content}

请从以下几个维度进行分析，并以 JSON 格式返回结果:

{{
    "themes": ["主题1", "主题2", ...],  // 今日3-5个主要工作/学习主题，每个主题10-20字
    "work_focus": "...",  // 全天工作重点回顾，150-200字，总结今天主要做了什么，核心任务是什么
    "current_interests": ["关注点1", "关注点2", ...],  // 用户当前关注的3-5个具体内容/技术/话题
    "insights": ["洞察1", "洞察2", ...],  // 3-5条洞察和启发，每条30-50字，可以是：
        // - 发现的工作模式或习惯
        // - 可能的改进方向
        // - 有趣的发现
        // - 深层次的思考和建议
    "detailed_summary": "..."  // 200-300字的详细总结，包含：
        // - 今天完成了什么
        // - 遇到了什么问题/挑战
        // - 取得了什么进展
        // - 整体工作状态评估
}}

分析要求:
1. 深入分析内容含义，而不是简单罗列
2. 识别隐藏的模式和趋势
3. 给出有价值的洞察，而不是泛泛而谈
4. 语气专业、友好、富有启发性
5. 必须返回有效的 JSON 格式
"""
        
        try:
            from .llm_backend import LLMMessage
            
            response = backend.chat(
                messages=[
                    LLMMessage(role="system", content="你是一个专业的个人效率分析师和工作教练，擅长从用户的日常输入中提取有价值的洞察，帮助用户更好地理解自己的工作模式和成长方向。请始终返回有效的 JSON 格式。"),
                    LLMMessage(role="user", content=prompt)
                ],
                max_tokens=1500,
                temperature=0.7,
            )
            
            result_text = response.content.strip()
            
            # 移除 Qwen 3 的思考标签 <think>...</think>
            import re
            result_text = re.sub(r'<think>.*?</think>', '', result_text, flags=re.DOTALL)
            result_text = result_text.strip()
            
            # 解析 JSON（处理可能的 markdown 代码块）
            if result_text.startswith("```"):
                # 移除 markdown 代码块标记
                lines = result_text.split("\n")
                result_text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            
            import json
            try:
                data = json.loads(result_text)
                return ThemeAnalysis(
                    themes=data.get("themes", []),
                    work_focus=data.get("work_focus", ""),
                    current_interests=data.get("current_interests", []),
                    insights=data.get("insights", []),
                    detailed_summary=data.get("detailed_summary", ""),
                )
            except json.JSONDecodeError as e:
                print(f"JSON 解析失败: {e}")
                # 尝试从文本中提取信息
                return ThemeAnalysis(
                    themes=[],
                    work_focus=result_text[:500] if result_text else "",
                    current_interests=[],
                    insights=[],
                    detailed_summary=result_text if result_text else "",
                )
        
        except Exception as e:
            print(f"主题分析失败: {e}")
            return None
    
    def generate_full_report(self, target_date: Optional[date] = None) -> DailyReport:
        """
        生成完整报告（包含主题深度分析）
        
        Args:
            target_date: 目标日期，默认今天
        
        Returns:
            包含主题分析的完整 DailyReport
        """
        # 生成基础报告
        report = self.generate_daily_report(target_date)
        
        # 如果 AI 可用，生成主题深度分析
        if config.ai_enabled:
            report.theme_analysis = self.generate_theme_analysis(target_date)
        
        return report


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

