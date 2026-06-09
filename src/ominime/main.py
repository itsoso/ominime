#!/usr/bin/env python3
"""
OmniMe - macOS 输入追踪系统

主入口文件
"""

import sys
import argparse
from datetime import date, datetime, timedelta

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from .keyboard_listener import check_accessibility_permission, request_accessibility_permission
from .database import get_database
from .analyzer import get_analyzer
from .config import config


console = Console()


def check_permissions():
    """检查并请求必要的权限"""
    if not check_accessibility_permission():
        console.print("[yellow]⚠️  需要辅助功能权限[/yellow]")
        console.print("正在打开系统偏好设置...")
        console.print("请在「隐私与安全性 → 辅助功能」中授予权限")
        request_accessibility_permission()
        return False
    return True


def cmd_start(args):
    """启动 Menu Bar 应用（旧版）"""
    console.print("[bold green]🚀 启动 OmniMe Menu Bar 应用...[/bold green]")
    
    if not check_permissions():
        console.print("[red]请授予权限后重新运行[/red]")
        return
    
    from .menu_bar import run_menu_bar_app
    run_menu_bar_app()


def cmd_app(args):
    """启动完整版桌面应用"""
    console.print("[bold green]🚀 启动 OmniMe 桌面应用...[/bold green]")
    
    if not check_permissions():
        console.print("[yellow]⚠️  未授予辅助功能权限，应用将启动但无法监听键盘输入[/yellow]")
        console.print("[yellow]可以在菜单栏中手动授予权限后开始记录[/yellow]")
    
    from .menu_bar_app import run_app
    run_app()


def cmd_monitor(args):
    """命令行监控模式"""
    console.print("[bold green]🔍 启动命令行监控模式...[/bold green]")
    
    if not check_permissions():
        console.print("[red]请授予权限后重新运行[/red]")
        return
    
    import time
    from .keyboard_listener import KeyboardListener, KeyEvent
    from .input_snapshot import normalize_submission_text, should_save_submission_snapshot
    from .submission_processor import save_submission_event
    
    db = get_database()
    
    current_app = [""]
    char_count = [0]
    last_submission_snapshot = [None]
    
    def on_key(event: KeyEvent):
        if not event.modifiers.get("submit_snapshot"):
            return
        
        if event.modifiers.get('cmd'):
            return
        
        if config.is_app_ignored(event.app_bundle_id):
            return

        content = normalize_submission_text(event.character)
        if not content:
            return

        now = time.monotonic()
        current_snapshot = (event.app_name, event.app_bundle_id, content)
        if not should_save_submission_snapshot(
            current_snapshot,
            last_submission_snapshot[0],
            now=now,
            debounce_seconds=0.8,
        ):
            return
        last_submission_snapshot[0] = (*current_snapshot, now)
        
        # 检测应用切换
        if current_app[0] != event.app_name:
            if current_app[0]:
                console.print("")
            current_app[0] = event.app_name
            console.print(f"\n[cyan][{event.app_name}][/cyan] ", end="")

        console.print(f"[green]{content}[/green]", end="")
        char_count[0] += len(content)

        save_submission_event(db, event, content)
    
    listener = KeyboardListener(on_key)
    listener.start()
    
    console.print("[green]✅ 监听已启动，按 Ctrl+C 停止[/green]")
    console.print(f"[dim]数据存储位置: {config.db_path}[/dim]")
    console.print("")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        console.print(f"\n\n[yellow]已停止，共记录 {char_count[0]} 个字符[/yellow]")


def cmd_report(args):
    """生成报告"""
    analyzer = get_analyzer()
    
    # 解析日期
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]日期格式错误: {args.date}，请使用 YYYY-MM-DD 格式[/red]")
            return
    else:
        target_date = date.today()
    
    # 生成报告
    report = analyzer.generate_daily_report(target_date)
    
    # 使用 rich 美化输出
    console.print()
    
    # 标题
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday = weekday_names[target_date.weekday()]
    title = f"📅 {target_date.strftime('%Y-%m-%d')} {weekday} 输入汇总"
    
    console.print(Panel(title, style="bold cyan"))
    
    # 概览表格
    overview_table = Table(show_header=False, box=None)
    overview_table.add_row("📊 总字符", f"{report.total_chars:,}")
    overview_table.add_row("📱 应用数", str(report.total_apps))
    overview_table.add_row("🔢 会话数", str(report.total_sessions))
    if report.total_time_minutes > 0:
        hours = int(report.total_time_minutes // 60)
        mins = int(report.total_time_minutes % 60)
        overview_table.add_row("⏱️  活跃时间", f"{hours}小时{mins}分钟")
    
    console.print(Panel(overview_table, title="概览"))
    
    # 应用统计表格
    if report.app_stats:
        app_table = Table(title="应用分布")
        app_table.add_column("应用", style="cyan")
        app_table.add_column("字符数", justify="right")
        app_table.add_column("占比", justify="right")
        app_table.add_column("进度条")
        
        for stat in report.app_stats[:10]:
            ratio = stat.total_chars / report.total_chars * 100 if report.total_chars > 0 else 0
            bar_len = int(ratio / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            app_table.add_row(
                stat.display_name,
                f"{stat.total_chars:,}",
                f"{ratio:.1f}%",
                bar
            )
        
        console.print(app_table)
    
    # 主线活动
    if report.main_activities:
        console.print()
        console.print("[bold]🎯 今日主线活动[/bold]")
        for i, activity in enumerate(report.main_activities, 1):
            console.print(f"  {i}. {activity}")
    
    # 总结
    console.print()
    console.print(Panel(report.summary, title="📝 总结"))
    
    # 建议
    if report.suggestions:
        console.print()
        console.print("[bold]💡 建议[/bold]")
        for suggestion in report.suggestions:
            console.print(f"  {suggestion}")
    
    console.print()


def cmd_stats(args):
    """查看统计"""
    db = get_database()
    
    # 最近7天汇总
    days_summary = db.get_recent_days_summary(7)
    
    if not days_summary:
        console.print("[yellow]暂无数据记录[/yellow]")
        return
    
    console.print()
    console.print("[bold cyan]📊 最近 7 天统计[/bold cyan]")
    console.print()
    
    table = Table()
    table.add_column("日期")
    table.add_column("字符数", justify="right")
    table.add_column("应用数", justify="right")
    table.add_column("会话数", justify="right")
    
    for day in days_summary:
        table.add_row(
            day['day'],
            f"{day['total_chars']:,}",
            str(day['app_count']),
            str(day['session_count']),
        )
    
    console.print(table)
    
    # 总计
    total = sum(d['total_chars'] for d in days_summary)
    avg = total / len(days_summary) if days_summary else 0
    console.print()
    console.print(f"[green]总计: {total:,} 字符 | 日均: {avg:,.0f} 字符[/green]")


def cmd_export(args):
    """导出数据"""
    import json
    from pathlib import Path
    
    db = get_database()
    
    # 解析日期范围
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]日期格式错误: {args.date}[/red]")
            return
    else:
        target_date = date.today()
    
    # 获取数据
    records = db.get_records_by_date(target_date)
    
    if not records:
        console.print(f"[yellow]{target_date} 没有记录[/yellow]")
        return
    
    # 准备导出数据
    export_data = {
        "date": target_date.isoformat(),
        "total_records": len(records),
        "total_chars": sum(r.char_count for r in records),
        "records": [
            {
                "timestamp": r.timestamp.isoformat(),
                "app_name": r.app_name,
                "display_name": r.display_name,
                "content": r.content,
                "char_count": r.char_count,
            }
            for r in records
        ]
    }
    
    # 写入文件
    output_path = Path(args.output) if args.output else Path(f"ominime_export_{target_date}.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    console.print(f"[green]✅ 已导出到 {output_path}[/green]")
    console.print(f"   记录数: {len(records)}, 字符数: {export_data['total_chars']:,}")


def cmd_web(args):
    """启动 Web 后台"""
    host = args.host or "127.0.0.1"
    port = args.port or 8001
    
    console.print(f"[bold green]🌐 启动 Web 后台管理...[/bold green]")
    console.print(f"[dim]访问地址: http://{host}:{port}[/dim]")
    console.print(f"[dim]API 文档: http://{host}:{port}/docs[/dim]")
    console.print()
    
    from .web.server import run_server
    run_server(host=host, port=port, reload=args.reload)


def cmd_obsidian(args):
    """导出到 Obsidian"""
    from .exporter import export_daily_to_obsidian
    
    # 解析日期
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]日期格式错误: {args.date}，请使用 YYYY-MM-DD 格式[/red]")
            return
    else:
        target_date = date.today()
    
    console.print(f"[bold green]📝 导出 {target_date} 的数据到 Obsidian...[/bold green]")
    
    # 导出选项
    include_raw = not args.no_raw
    include_ai = not args.no_ai
    
    filepath = export_daily_to_obsidian(
        target_date=target_date,
        include_raw_content=include_raw,
        include_ai_analysis=include_ai,
        obsidian_path=args.path
    )
    
    if filepath:
        console.print(f"[green]✅ 已导出到: {filepath}[/green]")
    else:
        console.print(f"[yellow]⚠️  {target_date} 没有输入记录[/yellow]")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="OmniMe - macOS 输入追踪系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  ominime              # 启动桌面应用（菜单栏）⭐
  ominime app          # 同上，启动完整版桌面应用
  ominime web          # 启动 Web 后台管理
  ominime monitor      # 命令行监控模式
  ominime report       # 查看今日报告
  ominime report -d 2026-01-07  # 查看指定日期报告
  ominime stats        # 查看统计
  ominime export       # 导出今日数据
  ominime obsidian     # 导出今日日报到 Obsidian ⭐
  ominime obsidian -d 2026-01-17  # 导出指定日期

安装开机启动:
  ./scripts/install_app.sh   # 一键安装并设置开机启动
  ./scripts/uninstall_app.sh # 卸载并移除开机启动
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # start 命令（旧版）
    start_parser = subparsers.add_parser("start", help="启动 Menu Bar 应用（旧版）")
    start_parser.set_defaults(func=cmd_start)
    
    # app 命令（推荐）
    app_parser = subparsers.add_parser("app", help="启动完整版桌面应用（推荐）⭐")
    app_parser.set_defaults(func=cmd_app)
    
    # web 命令
    web_parser = subparsers.add_parser("web", help="启动 Web 后台管理")
    web_parser.add_argument("-H", "--host", default="127.0.0.1", help="主机地址 (默认: 127.0.0.1)")
    web_parser.add_argument("-p", "--port", type=int, default=8001, help="端口号 (默认: 8001)")
    web_parser.add_argument("--reload", action="store_true", help="启用热重载 (开发模式)")
    web_parser.set_defaults(func=cmd_web)
    
    # obsidian 命令
    obsidian_parser = subparsers.add_parser("obsidian", help="导出日报到 Obsidian")
    obsidian_parser.add_argument("-d", "--date", help="日期 (YYYY-MM-DD)，默认今天")
    obsidian_parser.add_argument("-p", "--path", help="Obsidian vault 路径")
    obsidian_parser.add_argument("--no-raw", action="store_true", help="不包含原始输入内容")
    obsidian_parser.add_argument("--no-ai", action="store_true", help="不包含 AI 分析")
    obsidian_parser.set_defaults(func=cmd_obsidian)
    
    # monitor 命令
    monitor_parser = subparsers.add_parser("monitor", help="命令行监控模式")
    monitor_parser.set_defaults(func=cmd_monitor)
    
    # report 命令
    report_parser = subparsers.add_parser("report", help="生成报告")
    report_parser.add_argument("-d", "--date", help="日期 (YYYY-MM-DD)")
    report_parser.set_defaults(func=cmd_report)
    
    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="查看统计")
    stats_parser.set_defaults(func=cmd_stats)
    
    # export 命令
    export_parser = subparsers.add_parser("export", help="导出数据")
    export_parser.add_argument("-d", "--date", help="日期 (YYYY-MM-DD)")
    export_parser.add_argument("-o", "--output", help="输出文件路径")
    export_parser.set_defaults(func=cmd_export)
    
    args = parser.parse_args()
    
    # 如果没有子命令，默认启动完整版桌面应用
    if args.command is None:
        cmd_app(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
