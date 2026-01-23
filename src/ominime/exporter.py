"""
Obsidian 导出模块

将每日分析报告导出为 Markdown 文件保存到 Obsidian
"""

import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Dict, List

from .database import get_database
from .analyzer import get_analyzer, DailyReport, ThemeAnalysis
from .config import config
from .llm_backend import get_llm_backend


class ObsidianExporter:
    """
    Obsidian 导出器
    
    将每日输入记录和 AI 分析导出为 Markdown 文件
    """
    
    def __init__(self, obsidian_path: Optional[str] = None):
        """
        初始化导出器
        
        Args:
            obsidian_path: Obsidian vault 路径，默认从环境变量读取
        """
        self.obsidian_path = Path(
            obsidian_path or 
            os.getenv("OBSIDIAN_PATH") or 
            "/Users/liqiuhua/work/personal/obsidian/personal"
        )
        self.output_dir = self.obsidian_path / "10_Sources" / "OmniMe"
        self.db = get_database()
        self.analyzer = get_analyzer()
    
    def ensure_output_dir(self):
        """确保输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def export_daily_report(
        self, 
        target_date: Optional[date] = None,
        include_raw_content: bool = True,
        include_ai_analysis: bool = True
    ) -> Optional[Path]:
        """
        导出每日报告到 Obsidian
        
        Args:
            target_date: 目标日期，默认今天
            include_raw_content: 是否包含原始输入内容
            include_ai_analysis: 是否包含 AI 分析
        
        Returns:
            导出文件路径，如果无数据则返回 None
        """
        if target_date is None:
            target_date = date.today()
        
        self.ensure_output_dir()
        
        # 获取数据
        records = self.db.get_records_by_date(target_date)
        if not records:
            return None
        
        # 生成报告
        report = self.analyzer.generate_daily_report(target_date)
        
        # 生成主题分析
        theme_analysis = None
        if include_ai_analysis and config.ai_enabled:
            theme_analysis = self.analyzer.generate_theme_analysis(target_date)
        
        # 按应用分组内容
        app_contents = self._group_content_by_app(records)
        
        # 生成 Markdown 内容
        markdown = self._generate_markdown(
            target_date=target_date,
            report=report,
            theme_analysis=theme_analysis,
            app_contents=app_contents,
            include_raw_content=include_raw_content,
            include_ai_analysis=include_ai_analysis
        )
        
        # 获取模型名称
        model_name = self._get_model_name()
        
        # 保存文件
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday = weekday_names[target_date.weekday()]
        filename = f"{target_date.strftime('%Y-%m-%d')}-{weekday}-OmniMe日报-{model_name}.md"
        filepath = self.output_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)
        
        return filepath
    
    def _get_model_name(self) -> str:
        """获取当前使用的模型名称"""
        try:
            backend = get_llm_backend()
            if backend:
                backend_type = os.getenv("LLM_BACKEND", "openai")
                if backend_type == "ollama":
                    model = os.getenv("OLLAMA_MODEL", "unknown")
                    return model.replace(":", "-")
                elif backend_type == "qwen-local":
                    model = os.getenv("QWEN_MODEL", "qwen-local")
                    return model.split("/")[-1] if "/" in model else model
                elif backend_type == "openai":
                    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
                    return model
            return "no-ai"
        except Exception:
            return "no-ai"
    
    def _group_content_by_app(self, records) -> Dict[str, Dict]:
        """按应用分组内容"""
        app_contents = {}
        
        for record in records:
            app_name = record.display_name or record.app_name
            if app_name not in app_contents:
                app_contents[app_name] = {
                    "total_chars": 0,
                    "sessions": [],
                    "contents": []
                }
            
            app_contents[app_name]["total_chars"] += record.char_count
            if record.content and record.content.strip():
                app_contents[app_name]["contents"].append({
                    "time": record.timestamp.strftime("%H:%M:%S"),
                    "content": record.content.strip()
                })
        
        # 按字符数排序
        return dict(sorted(
            app_contents.items(), 
            key=lambda x: x[1]["total_chars"], 
            reverse=True
        ))
    
    def _generate_markdown(
        self,
        target_date: date,
        report: DailyReport,
        theme_analysis: Optional[ThemeAnalysis],
        app_contents: Dict[str, Dict],
        include_raw_content: bool,
        include_ai_analysis: bool
    ) -> str:
        """生成 Markdown 内容"""
        lines = []
        
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday = weekday_names[target_date.weekday()]
        
        # 获取模型名称
        model_name = self._get_model_name()
        
        # YAML Front Matter
        lines.append("---")
        lines.append(f"date: {target_date.isoformat()}")
        lines.append(f"weekday: {weekday}")
        lines.append(f"total_chars: {report.total_chars}")
        lines.append(f"total_apps: {report.total_apps}")
        lines.append(f"total_sessions: {report.total_sessions}")
        lines.append(f"ai_model: {model_name}")
        lines.append(f"created: {datetime.now().isoformat()}")
        lines.append("tags:")
        lines.append("  - OmniMe")
        lines.append("  - 日报")
        lines.append("  - 输入追踪")
        lines.append(f"  - {model_name}")
        lines.append("---")
        lines.append("")
        
        # 标题
        lines.append(f"# 📅 {target_date.strftime('%Y-%m-%d')} {weekday} 输入日报")
        lines.append("")
        
        # 概览
        lines.append("## 📊 今日概览")
        lines.append("")
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 📝 总字符数 | {report.total_chars:,} |")
        lines.append(f"| 📱 应用数量 | {report.total_apps} |")
        lines.append(f"| 🔢 会话数量 | {report.total_sessions} |")
        
        if report.total_time_minutes > 0:
            hours = int(report.total_time_minutes // 60)
            mins = int(report.total_time_minutes % 60)
            time_str = f"{hours}小时{mins}分钟" if hours > 0 else f"{mins}分钟"
            lines.append(f"| ⏱️ 活跃时间 | {time_str} |")
        
        lines.append("")
        
        # 应用分布
        if report.app_stats:
            lines.append("## 📱 应用分布")
            lines.append("")
            lines.append("| 应用 | 字符数 | 占比 |")
            lines.append("|------|--------|------|")
            
            for stat in report.app_stats[:10]:
                percentage = stat.total_chars / report.total_chars * 100 if report.total_chars > 0 else 0
                lines.append(f"| {stat.display_name} | {stat.total_chars:,} | {percentage:.1f}% |")
            
            lines.append("")
        
        # 主线活动
        if report.main_activities:
            lines.append("## 🎯 主线活动")
            lines.append("")
            for i, activity in enumerate(report.main_activities, 1):
                lines.append(f"{i}. {activity}")
            lines.append("")
        
        # AI 分析部分
        if include_ai_analysis:
            # 基础总结
            if report.summary:
                lines.append("## 📝 每日总结")
                lines.append("")
                lines.append(report.summary)
                lines.append("")
            
            # 主题深度分析
            if theme_analysis:
                lines.append("## 🎯 主题深度分析")
                lines.append("")
                
                # 今日主题
                if theme_analysis.themes:
                    lines.append("### 今日主题")
                    lines.append("")
                    for theme in theme_analysis.themes:
                        lines.append(f"- {theme}")
                    lines.append("")
                
                # 工作重点回顾
                if theme_analysis.work_focus:
                    lines.append("### 工作重点回顾")
                    lines.append("")
                    lines.append(theme_analysis.work_focus)
                    lines.append("")
                
                # 当前关注
                if theme_analysis.current_interests:
                    lines.append("### 当前关注")
                    lines.append("")
                    for interest in theme_analysis.current_interests:
                        lines.append(f"- {interest}")
                    lines.append("")
                
                # 洞察与启发
                if theme_analysis.insights:
                    lines.append("### 💡 洞察与启发")
                    lines.append("")
                    for insight in theme_analysis.insights:
                        lines.append(f"- ✨ {insight}")
                    lines.append("")
                
                # 详细总结
                if theme_analysis.detailed_summary:
                    lines.append("### 深度总结")
                    lines.append("")
                    lines.append(theme_analysis.detailed_summary)
                    lines.append("")
            
            # AI 工作分析
            if report.ai_work_analysis:
                lines.append("## 🤖 AI 工作分析")
                lines.append("")
                lines.append(report.ai_work_analysis)
                lines.append("")
            
            # 建议
            if report.suggestions:
                lines.append("## 💡 优化建议")
                lines.append("")
                for suggestion in report.suggestions:
                    lines.append(f"- {suggestion}")
                lines.append("")
        
        # 工作路径分析
        if report.work_path:
            lines.append("## 🛤️ 工作路径分析")
            lines.append("")
            lines.append(f"- **工作模式**: {report.work_path.work_pattern}")
            lines.append(f"- **效率分数**: {report.work_path.efficiency_score:.1f}/100")
            lines.append(f"- **应用切换**: {report.work_path.app_switches} 次")
            lines.append(f"- **工作片段**: {report.work_path.total_segments} 个")
            lines.append("")
            
            # 峰值时段
            if report.work_path.peak_hours:
                lines.append("### ⏰ 峰值时段")
                lines.append("")
                for hour, chars in report.work_path.peak_hours[:5]:
                    lines.append(f"- {hour}:00 - {chars:,} 字符")
                lines.append("")
            
            # 专注时段
            if report.work_path.focus_periods:
                lines.append("### 🎯 深度工作时段")
                lines.append("")
                for start, end, app in report.work_path.focus_periods[:5]:
                    duration = (end - start).total_seconds() / 60
                    lines.append(f"- {start.strftime('%H:%M')}-{end.strftime('%H:%M')} {app} ({duration:.0f}分钟)")
                lines.append("")
        
        # 原始输入内容
        if include_raw_content and app_contents:
            lines.append("---")
            lines.append("")
            lines.append("## 📄 原始输入内容")
            lines.append("")
            lines.append("> [!note] 说明")
            lines.append("> 以下是按应用分组的原始输入内容，用于回顾和检索。")
            lines.append("")
            
            for app_name, data in app_contents.items():
                lines.append(f"### {app_name}")
                lines.append("")
                lines.append(f"*{data['total_chars']:,} 字符*")
                lines.append("")
                
                # 合并内容
                if data["contents"]:
                    lines.append("```")
                    for item in data["contents"]:
                        content = item["content"]
                        # 限制单条内容长度
                        if len(content) > 500:
                            content = content[:500] + "..."
                        lines.append(f"[{item['time']}] {content}")
                    lines.append("```")
                    lines.append("")
        
        # 页脚
        lines.append("---")
        lines.append("")
        lines.append(f"*由 OmniMe 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | AI 模型: {model_name}*")
        
        return "\n".join(lines)


# 全局导出器实例
_exporter_instance: Optional[ObsidianExporter] = None


def get_exporter(obsidian_path: Optional[str] = None) -> ObsidianExporter:
    """获取导出器单例"""
    global _exporter_instance
    if _exporter_instance is None:
        _exporter_instance = ObsidianExporter(obsidian_path)
    return _exporter_instance


def export_daily_to_obsidian(
    target_date: Optional[date] = None,
    include_raw_content: bool = True,
    include_ai_analysis: bool = True,
    obsidian_path: Optional[str] = None
) -> Optional[Path]:
    """
    便捷函数：导出每日报告到 Obsidian
    
    Args:
        target_date: 目标日期，默认今天
        include_raw_content: 是否包含原始输入内容
        include_ai_analysis: 是否包含 AI 分析
        obsidian_path: Obsidian vault 路径
    
    Returns:
        导出文件路径，如果无数据则返回 None
    """
    exporter = ObsidianExporter(obsidian_path) if obsidian_path else get_exporter()
    return exporter.export_daily_report(
        target_date=target_date,
        include_raw_content=include_raw_content,
        include_ai_analysis=include_ai_analysis
    )
