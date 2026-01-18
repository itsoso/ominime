"""
Web API 模块

提供 RESTful API 接口
"""

from datetime import date, datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import os
from pathlib import Path

from ..database import get_database, InputRecord
from ..analyzer import get_analyzer
from ..config import config


# 创建 FastAPI 应用
app = FastAPI(
    title="OmniMe API",
    description="macOS 输入追踪系统 Web API",
    version="0.1.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Pydantic 模型 =====

class AppStatsResponse(BaseModel):
    app_name: str
    display_name: str
    total_chars: int
    session_count: int
    total_time_minutes: float
    percentage: float


class DailyOverview(BaseModel):
    date: str
    weekday: str
    total_chars: int
    total_apps: int
    total_sessions: int
    total_time_minutes: float


class WorkPathSegmentResponse(BaseModel):
    start_time: str
    end_time: str
    app_name: str
    display_name: str
    char_count: int
    duration_minutes: float
    content_preview: str


class WorkPathAnalysisResponse(BaseModel):
    total_segments: int
    app_switches: int
    peak_hours: List[dict]
    focus_periods: List[dict]
    work_pattern: str
    efficiency_score: float
    segments: Optional[List[WorkPathSegmentResponse]] = None


class DailyReportResponse(BaseModel):
    overview: DailyOverview
    app_stats: List[AppStatsResponse]
    main_activities: List[str]
    summary: str
    suggestions: List[str]
    work_path: Optional[WorkPathAnalysisResponse] = None
    ai_work_analysis: Optional[str] = None


class HourlyStats(BaseModel):
    hour: int
    chars: int


class WeeklyTrend(BaseModel):
    date: str
    weekday: str
    total_chars: int
    app_count: int


class RecordItem(BaseModel):
    id: int
    timestamp: str
    app_name: str
    display_name: str
    content: str
    char_count: int


class StatusResponse(BaseModel):
    status: str
    is_recording: bool
    today_chars: int
    db_path: str
    data_dir: str


class ThemeAnalysisResponse(BaseModel):
    themes: List[str]
    work_focus: str
    current_interests: List[str]
    insights: List[str]
    detailed_summary: str


class FullReportResponse(BaseModel):
    overview: DailyOverview
    app_stats: List[AppStatsResponse]
    main_activities: List[str]
    summary: str
    suggestions: List[str]
    work_path: Optional[WorkPathAnalysisResponse] = None
    ai_work_analysis: Optional[str] = None
    theme_analysis: Optional[ThemeAnalysisResponse] = None


# ===== API 路由 =====

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """获取系统状态"""
    db = get_database()
    today_chars = db.get_total_chars_today()
    
    return StatusResponse(
        status="running",
        is_recording=False,  # Web 模式下默认不显示录制状态
        today_chars=today_chars,
        db_path=str(config.db_path),
        data_dir=str(config.data_dir),
    )


@app.get("/api/overview")
async def get_overview():
    """获取总体概览"""
    db = get_database()
    
    # 今日统计
    today = date.today()
    today_stats = db.get_daily_stats(today)
    today_chars = sum(s.total_chars for s in today_stats)
    
    # 昨日统计
    yesterday = today - timedelta(days=1)
    yesterday_stats = db.get_daily_stats(yesterday)
    yesterday_chars = sum(s.total_chars for s in yesterday_stats)
    
    # 本周统计
    week_start = today - timedelta(days=today.weekday())
    week_data = db.get_recent_days_summary(7)
    week_chars = sum(d.get('total_chars', 0) for d in week_data)
    
    # 计算变化
    if yesterday_chars > 0:
        change_percent = ((today_chars - yesterday_chars) / yesterday_chars) * 100
    else:
        change_percent = 100 if today_chars > 0 else 0
    
    return {
        "today": {
            "chars": today_chars,
            "apps": len(today_stats),
            "change_percent": round(change_percent, 1),
        },
        "yesterday": {
            "chars": yesterday_chars,
            "apps": len(yesterday_stats),
        },
        "week": {
            "chars": week_chars,
            "avg_per_day": round(week_chars / max(len(week_data), 1)),
        }
    }


@app.get("/api/report/{target_date}", response_model=DailyReportResponse)
async def get_daily_report(target_date: str):
    """获取指定日期的报告"""
    try:
        report_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")
    
    analyzer = get_analyzer()
    report = analyzer.generate_daily_report(report_date)
    
    # 计算百分比
    total_chars = report.total_chars or 1
    app_stats = [
        AppStatsResponse(
            app_name=s.app_name,
            display_name=s.display_name,
            total_chars=s.total_chars,
            session_count=s.session_count,
            total_time_minutes=round(s.total_time_minutes, 1),
            percentage=round(s.total_chars / total_chars * 100, 1),
        )
        for s in report.app_stats
    ]
    
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    # 工作路径分析
    work_path_response = None
    if report.work_path:
        work_path_response = WorkPathAnalysisResponse(
            total_segments=report.work_path.total_segments,
            app_switches=report.work_path.app_switches,
            peak_hours=[{"hour": h, "chars": c} for h, c in report.work_path.peak_hours],
            focus_periods=[
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "app": app,
                    "duration_minutes": round((end - start).total_seconds() / 60, 1)
                }
                for start, end, app in report.work_path.focus_periods
            ],
            work_pattern=report.work_path.work_pattern,
            efficiency_score=round(report.work_path.efficiency_score, 1),
            segments=[
                WorkPathSegmentResponse(
                    start_time=seg.start_time.isoformat(),
                    end_time=seg.end_time.isoformat(),
                    app_name=seg.app_name,
                    display_name=seg.display_name,
                    char_count=seg.char_count,
                    duration_minutes=round(seg.duration_minutes, 1),
                    content_preview=seg.content_preview
                )
                for seg in report.work_path.segments[:50]  # 限制返回数量
            ] if len(report.work_path.segments) <= 50 else None
        )
    
    return DailyReportResponse(
        overview=DailyOverview(
            date=report_date.isoformat(),
            weekday=weekday_names[report_date.weekday()],
            total_chars=report.total_chars,
            total_apps=report.total_apps,
            total_sessions=report.total_sessions,
            total_time_minutes=round(report.total_time_minutes, 1),
        ),
        app_stats=app_stats,
        main_activities=report.main_activities,
        summary=report.summary,
        suggestions=report.suggestions,
        work_path=work_path_response,
        ai_work_analysis=report.ai_work_analysis,
    )


@app.get("/api/report")
async def get_today_report():
    """获取今日报告"""
    return await get_daily_report(date.today().isoformat())


@app.get("/api/analysis/theme/{target_date}", response_model=Optional[ThemeAnalysisResponse])
async def get_theme_analysis(target_date: str):
    """
    获取指定日期的主题深度分析
    
    分析用户全部输入内容，生成：
    - 今日主题列表
    - 工作重点回顾
    - 当前关注的内容
    - 洞察和启发
    - 详细总结
    """
    try:
        report_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")
    
    analyzer = get_analyzer()
    theme = analyzer.generate_theme_analysis(report_date)
    
    if not theme:
        return None
    
    return ThemeAnalysisResponse(
        themes=theme.themes,
        work_focus=theme.work_focus,
        current_interests=theme.current_interests,
        insights=theme.insights,
        detailed_summary=theme.detailed_summary,
    )


@app.get("/api/analysis/theme")
async def get_today_theme_analysis():
    """获取今日主题深度分析"""
    return await get_theme_analysis(date.today().isoformat())


@app.get("/api/report/full/{target_date}", response_model=FullReportResponse)
async def get_full_report(target_date: str):
    """
    获取完整报告（包含主题深度分析）
    
    包含：
    - 基础统计概览
    - 应用统计
    - 工作路径分析
    - AI 工作分析
    - 主题深度分析（今日主题、工作重点、关注内容、洞察启发）
    """
    try:
        report_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")
    
    analyzer = get_analyzer()
    report = analyzer.generate_full_report(report_date)
    
    # 计算百分比
    total_chars = report.total_chars or 1
    app_stats = [
        AppStatsResponse(
            app_name=s.app_name,
            display_name=s.display_name,
            total_chars=s.total_chars,
            session_count=s.session_count,
            total_time_minutes=round(s.total_time_minutes, 1),
            percentage=round(s.total_chars / total_chars * 100, 1),
        )
        for s in report.app_stats
    ]
    
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    # 工作路径分析
    work_path_response = None
    if report.work_path:
        work_path_response = WorkPathAnalysisResponse(
            total_segments=report.work_path.total_segments,
            app_switches=report.work_path.app_switches,
            peak_hours=[{"hour": h, "chars": c} for h, c in report.work_path.peak_hours],
            focus_periods=[
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "app": app,
                    "duration_minutes": round((end - start).total_seconds() / 60, 1)
                }
                for start, end, app in report.work_path.focus_periods
            ],
            work_pattern=report.work_path.work_pattern,
            efficiency_score=round(report.work_path.efficiency_score, 1),
            segments=None
        )
    
    # 主题分析
    theme_response = None
    if report.theme_analysis:
        theme_response = ThemeAnalysisResponse(
            themes=report.theme_analysis.themes,
            work_focus=report.theme_analysis.work_focus,
            current_interests=report.theme_analysis.current_interests,
            insights=report.theme_analysis.insights,
            detailed_summary=report.theme_analysis.detailed_summary,
        )
    
    return FullReportResponse(
        overview=DailyOverview(
            date=report_date.isoformat(),
            weekday=weekday_names[report_date.weekday()],
            total_chars=report.total_chars,
            total_apps=report.total_apps,
            total_sessions=report.total_sessions,
            total_time_minutes=round(report.total_time_minutes, 1),
        ),
        app_stats=app_stats,
        main_activities=report.main_activities,
        summary=report.summary,
        suggestions=report.suggestions,
        work_path=work_path_response,
        ai_work_analysis=report.ai_work_analysis,
        theme_analysis=theme_response,
    )


@app.get("/api/report/full")
async def get_today_full_report():
    """获取今日完整报告"""
    return await get_full_report(date.today().isoformat())


@app.get("/api/stats/hourly")
async def get_hourly_stats(target_date: Optional[str] = None):
    """获取每小时统计"""
    if target_date:
        try:
            report_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误")
    else:
        report_date = date.today()
    
    db = get_database()
    records = db.get_records_by_date(report_date)
    
    # 按小时汇总
    hourly = {h: 0 for h in range(24)}
    for record in records:
        hour = record.timestamp.hour
        hourly[hour] += record.char_count
    
    return [HourlyStats(hour=h, chars=c) for h, c in hourly.items()]


@app.get("/api/stats/weekly")
async def get_weekly_stats():
    """获取最近7天统计"""
    db = get_database()
    days = db.get_recent_days_summary(7)
    
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    result = []
    for day in days:
        d = datetime.strptime(day['day'], "%Y-%m-%d").date()
        result.append(WeeklyTrend(
            date=day['day'],
            weekday=weekday_names[d.weekday()],
            total_chars=day['total_chars'],
            app_count=day['app_count'],
        ))
    
    return result


@app.get("/api/stats/apps")
async def get_app_stats(
    target_date: Optional[str] = None,
    days: int = Query(default=1, ge=1, le=30)
):
    """获取应用统计"""
    db = get_database()
    
    if target_date:
        try:
            end_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误")
    else:
        end_date = date.today()
    
    # 汇总多天数据
    all_stats = {}
    for i in range(days):
        d = end_date - timedelta(days=i)
        day_stats = db.get_daily_stats(d)
        for s in day_stats:
            if s.display_name not in all_stats:
                all_stats[s.display_name] = {
                    "app_name": s.app_name,
                    "display_name": s.display_name,
                    "total_chars": 0,
                    "session_count": 0,
                    "total_time_minutes": 0,
                }
            all_stats[s.display_name]["total_chars"] += s.total_chars
            all_stats[s.display_name]["session_count"] += s.session_count
            all_stats[s.display_name]["total_time_minutes"] += s.total_time_minutes
    
    # 排序并计算百分比
    total = sum(s["total_chars"] for s in all_stats.values()) or 1
    result = sorted(all_stats.values(), key=lambda x: x["total_chars"], reverse=True)
    
    for s in result:
        s["percentage"] = round(s["total_chars"] / total * 100, 1)
        s["total_time_minutes"] = round(s["total_time_minutes"], 1)
    
    return result


@app.get("/api/records")
async def get_records(
    target_date: Optional[str] = None,
    app: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """获取输入记录列表"""
    db = get_database()
    
    if target_date:
        try:
            report_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误")
    else:
        report_date = date.today()
    
    records = db.get_records_by_date(report_date)
    
    # 过滤应用
    if app:
        records = [r for r in records if r.display_name == app or r.app_name == app]
    
    # 分页
    total = len(records)
    records = records[offset:offset + limit]
    
    return {
        "total": total,
        "records": [
            RecordItem(
                id=r.id,
                timestamp=r.timestamp.isoformat(),
                app_name=r.app_name,
                display_name=r.display_name,
                content=r.content[:200] if r.content else "",  # 限制长度
                char_count=r.char_count,
            )
            for r in records
        ]
    }


@app.get("/api/apps")
async def get_app_list():
    """获取所有应用列表"""
    db = get_database()
    
    # 获取最近30天的应用
    apps = set()
    for i in range(30):
        d = date.today() - timedelta(days=i)
        stats = db.get_daily_stats(d)
        for s in stats:
            apps.add((s.app_name, s.display_name))
    
    return [{"app_name": a, "display_name": d} for a, d in sorted(apps, key=lambda x: x[1])]


@app.get("/api/content/by-app")
async def get_content_by_app(target_date: Optional[str] = None):
    """获取按应用分组的完整输入内容"""
    db = get_database()
    
    if target_date:
        try:
            report_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误")
    else:
        report_date = date.today()
    
    records = db.get_records_by_date(report_date)
    
    # 按应用分组
    app_contents = {}
    for r in records:
        display_name = r.display_name
        if display_name not in app_contents:
            app_contents[display_name] = {
                "app_name": r.app_name,
                "display_name": display_name,
                "total_chars": 0,
                "sessions": []
            }
        
        app_contents[display_name]["total_chars"] += r.char_count
        app_contents[display_name]["sessions"].append({
            "time": r.timestamp.strftime("%H:%M:%S"),
            "content": r.content or "",
            "char_count": r.char_count,
        })
    
    # 合并每个应用的内容为完整文本
    result = []
    for app_name, data in sorted(app_contents.items(), key=lambda x: -x[1]["total_chars"]):
        # 合并所有 session 的内容（智能处理空格和换行）
        full_content = ""
        for session in data["sessions"]:
            content = session["content"] or ""
            if content:
                # 如果当前内容以换行开头或上一个内容以换行结尾，直接拼接
                # 否则检查是否需要添加空格（英文之间）或直接拼接（中文）
                if full_content and not full_content.endswith('\n') and not content.startswith('\n'):
                    # 检查是否都是 ASCII（英文），如果是则加空格
                    last_char = full_content[-1] if full_content else ''
                    first_char = content[0] if content else ''
                    
                    # 如果都是 ASCII 字母/数字，可能需要空格
                    # 如果有一方是中文，不加空格
                    if last_char.isascii() and first_char.isascii() and last_char.isalnum() and first_char.isalnum():
                        full_content += " " + content
                    else:
                        full_content += content
                else:
                    full_content += content
        
        result.append({
            "app_name": data["app_name"],
            "display_name": data["display_name"],
            "total_chars": data["total_chars"],
            "session_count": len(data["sessions"]),
            "full_content": full_content,
            "sessions": data["sessions"],
        })
    
    return result


# ===== 静态文件和首页 =====

# 获取 web 目录路径
WEB_DIR = Path(__file__).parent


@app.get("/", response_class=HTMLResponse)
async def index():
    """首页"""
    html_path = WEB_DIR / "templates" / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>OmniMe Web Dashboard</h1><p>请确保 templates/index.html 存在</p>")


# 挂载静态文件
static_dir = WEB_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

