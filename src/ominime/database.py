"""
数据库模块

使用 SQLite 存储输入记录和统计数据
"""

import sqlite3
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path

from .config import config


@dataclass
class InputRecord:
    """输入记录"""
    id: Optional[int]
    timestamp: datetime
    app_name: str
    app_bundle_id: str
    display_name: str
    content: str
    char_count: int
    session_id: str
    duration_seconds: float


@dataclass
class DailySummary:
    """每日汇总"""
    id: Optional[int]
    date: date
    app_name: str
    app_bundle_id: str
    display_name: str
    total_chars: int
    session_count: int
    total_time_seconds: float
    content_summary: Optional[str]
    suggestions: Optional[str]


@dataclass
class AppDailyStats:
    """应用每日统计"""
    app_name: str
    display_name: str
    total_chars: int
    session_count: int
    total_time_minutes: float
    sample_content: List[str]


class Database:
    """
    数据库管理类
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.db_path
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 输入记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS input_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    app_name TEXT NOT NULL,
                    app_bundle_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    content TEXT,
                    char_count INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    duration_seconds REAL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 每日汇总表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    app_name TEXT NOT NULL,
                    app_bundle_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    total_chars INTEGER NOT NULL,
                    session_count INTEGER DEFAULT 1,
                    total_time_seconds REAL DEFAULT 0,
                    content_summary TEXT,
                    suggestions TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, app_bundle_id)
                )
            """)
            
            # 全局每日汇总表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS global_daily_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL UNIQUE,
                    total_chars INTEGER NOT NULL,
                    total_apps INTEGER NOT NULL,
                    total_sessions INTEGER NOT NULL,
                    total_time_seconds REAL DEFAULT 0,
                    main_activities TEXT,
                    summary TEXT,
                    suggestions TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_input_records_timestamp 
                ON input_records(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_input_records_app 
                ON input_records(app_bundle_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_summaries_date 
                ON daily_summaries(date)
            """)
    
    # ===== 输入记录操作 =====
    
    def save_input_record(self, record: InputRecord) -> int:
        """保存输入记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO input_records 
                (timestamp, app_name, app_bundle_id, display_name, content, 
                 char_count, session_id, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.timestamp.isoformat(),
                record.app_name,
                record.app_bundle_id,
                record.display_name,
                record.content,
                record.char_count,
                record.session_id,
                record.duration_seconds,
            ))
            return cursor.lastrowid
    
    def get_records_by_date(self, target_date: date) -> List[InputRecord]:
        """获取指定日期的所有记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            start = datetime.combine(target_date, datetime.min.time())
            end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
            
            cursor.execute("""
                SELECT * FROM input_records 
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY timestamp
            """, (start.isoformat(), end.isoformat()))
            
            return [self._row_to_input_record(row) for row in cursor.fetchall()]
    
    def get_records_by_app(self, app_bundle_id: str, target_date: Optional[date] = None) -> List[InputRecord]:
        """获取指定应用的记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if target_date:
                start = datetime.combine(target_date, datetime.min.time())
                end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
                cursor.execute("""
                    SELECT * FROM input_records 
                    WHERE app_bundle_id = ? AND timestamp >= ? AND timestamp < ?
                    ORDER BY timestamp
                """, (app_bundle_id, start.isoformat(), end.isoformat()))
            else:
                cursor.execute("""
                    SELECT * FROM input_records 
                    WHERE app_bundle_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1000
                """, (app_bundle_id,))
            
            return [self._row_to_input_record(row) for row in cursor.fetchall()]
    
    def _row_to_input_record(self, row) -> InputRecord:
        """将数据库行转换为 InputRecord"""
        return InputRecord(
            id=row['id'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            app_name=row['app_name'],
            app_bundle_id=row['app_bundle_id'],
            display_name=row['display_name'],
            content=row['content'],
            char_count=row['char_count'],
            session_id=row['session_id'],
            duration_seconds=row['duration_seconds'],
        )
    
    # ===== 每日汇总操作 =====
    
    def save_daily_summary(self, summary: DailySummary):
        """保存每日汇总（使用 upsert）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_summaries 
                (date, app_name, app_bundle_id, display_name, total_chars, 
                 session_count, total_time_seconds, content_summary, suggestions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, app_bundle_id) DO UPDATE SET
                    total_chars = excluded.total_chars,
                    session_count = excluded.session_count,
                    total_time_seconds = excluded.total_time_seconds,
                    content_summary = excluded.content_summary,
                    suggestions = excluded.suggestions
            """, (
                summary.date.isoformat(),
                summary.app_name,
                summary.app_bundle_id,
                summary.display_name,
                summary.total_chars,
                summary.session_count,
                summary.total_time_seconds,
                summary.content_summary,
                summary.suggestions,
            ))
    
    def get_daily_summaries(self, target_date: date) -> List[DailySummary]:
        """获取指定日期的所有应用汇总"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM daily_summaries 
                WHERE date = ?
                ORDER BY total_chars DESC
            """, (target_date.isoformat(),))
            
            return [self._row_to_daily_summary(row) for row in cursor.fetchall()]
    
    def _row_to_daily_summary(self, row) -> DailySummary:
        """将数据库行转换为 DailySummary"""
        return DailySummary(
            id=row['id'],
            date=date.fromisoformat(row['date']),
            app_name=row['app_name'],
            app_bundle_id=row['app_bundle_id'],
            display_name=row['display_name'],
            total_chars=row['total_chars'],
            session_count=row['session_count'],
            total_time_seconds=row['total_time_seconds'],
            content_summary=row['content_summary'],
            suggestions=row['suggestions'],
        )
    
    # ===== 全局汇总操作 =====
    
    def save_global_daily_summary(
        self,
        target_date: date,
        total_chars: int,
        total_apps: int,
        total_sessions: int,
        total_time_seconds: float,
        main_activities: str,
        summary: str,
        suggestions: str,
    ):
        """保存全局每日汇总"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO global_daily_summaries 
                (date, total_chars, total_apps, total_sessions, total_time_seconds,
                 main_activities, summary, suggestions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_chars = excluded.total_chars,
                    total_apps = excluded.total_apps,
                    total_sessions = excluded.total_sessions,
                    total_time_seconds = excluded.total_time_seconds,
                    main_activities = excluded.main_activities,
                    summary = excluded.summary,
                    suggestions = excluded.suggestions
            """, (
                target_date.isoformat(),
                total_chars,
                total_apps,
                total_sessions,
                total_time_seconds,
                main_activities,
                summary,
                suggestions,
            ))
    
    def get_global_daily_summary(self, target_date: date) -> Optional[Dict]:
        """获取全局每日汇总"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM global_daily_summaries 
                WHERE date = ?
            """, (target_date.isoformat(),))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    # ===== 统计查询 =====
    
    def get_daily_stats(self, target_date: date) -> List[AppDailyStats]:
        """获取指定日期的应用统计"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            start = datetime.combine(target_date, datetime.min.time())
            end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
            
            # 按应用汇总
            cursor.execute("""
                SELECT 
                    app_name,
                    display_name,
                    SUM(char_count) as total_chars,
                    COUNT(DISTINCT session_id) as session_count
                FROM input_records 
                WHERE timestamp >= ? AND timestamp < ?
                GROUP BY app_bundle_id
                ORDER BY total_chars DESC
            """, (start.isoformat(), end.isoformat()))
            
            stats = []
            for row in cursor.fetchall():
                # 获取样本内容
                cursor.execute("""
                    SELECT content FROM input_records 
                    WHERE timestamp >= ? AND timestamp < ? 
                    AND app_name = ? AND content IS NOT NULL AND LENGTH(content) > 10
                    ORDER BY char_count DESC
                    LIMIT 5
                """, (start.isoformat(), end.isoformat(), row['app_name']))
                
                samples = [r['content'] for r in cursor.fetchall()]
                
                # 计算该应用的实际活跃时间（按会话）
                cursor.execute("""
                    SELECT 
                        session_id,
                        MIN(timestamp) as session_start,
                        MAX(timestamp) as session_end
                    FROM input_records
                    WHERE timestamp >= ? AND timestamp < ? AND app_name = ?
                    GROUP BY session_id
                """, (start.isoformat(), end.isoformat(), row['app_name']))
                
                total_minutes = 0.0
                for session in cursor.fetchall():
                    start_time = datetime.fromisoformat(session['session_start'])
                    end_time = datetime.fromisoformat(session['session_end'])
                    # 会话时长 = 最后一条记录时间 - 第一条记录时间 + 1 分钟
                    duration = (end_time - start_time).total_seconds() / 60.0 + 1.0
                    total_minutes += duration
                
                stats.append(AppDailyStats(
                    app_name=row['app_name'],
                    display_name=row['display_name'],
                    total_chars=row['total_chars'],
                    session_count=row['session_count'],
                    total_time_minutes=total_minutes,
                    sample_content=samples,
                ))
            
            return stats
    
    def get_total_chars_today(self) -> int:
        """获取今日总字符数"""
        today = date.today()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            start = datetime.combine(today, datetime.min.time())
            end = datetime.combine(today + timedelta(days=1), datetime.min.time())
            
            cursor.execute("""
                SELECT COALESCE(SUM(char_count), 0) as total
                FROM input_records 
                WHERE timestamp >= ? AND timestamp < ?
            """, (start.isoformat(), end.isoformat()))
            
            return cursor.fetchone()['total']
    
    def get_recent_days_summary(self, days: int = 7) -> List[Dict]:
        """获取最近几天的汇总"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            start_date = date.today() - timedelta(days=days-1)
            
            cursor.execute("""
                SELECT 
                    DATE(timestamp) as day,
                    SUM(char_count) as total_chars,
                    COUNT(DISTINCT app_bundle_id) as app_count,
                    COUNT(DISTINCT session_id) as session_count
                FROM input_records 
                WHERE DATE(timestamp) >= ?
                GROUP BY DATE(timestamp)
                ORDER BY day DESC
            """, (start_date.isoformat(),))
            
            return [dict(row) for row in cursor.fetchall()]


# 单例数据库实例
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """获取数据库单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


# 测试代码
if __name__ == "__main__":
    db = get_database()
    
    # 测试保存记录
    record = InputRecord(
        id=None,
        timestamp=datetime.now(),
        app_name="Cursor",
        app_bundle_id="com.todesktop.230313mzl4w4u92",
        display_name="Cursor",
        content="Hello, World!",
        char_count=13,
        session_id="test-session-1",
        duration_seconds=5.0,
    )
    
    record_id = db.save_input_record(record)
    print(f"保存记录 ID: {record_id}")
    
    # 测试查询
    today = date.today()
    records = db.get_records_by_date(today)
    print(f"今日记录数: {len(records)}")
    
    stats = db.get_daily_stats(today)
    print(f"今日应用统计: {stats}")

