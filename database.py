import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional


class CalendarDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS periods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    progesterone_start TEXT,
                    progesterone_stop TEXT,
                    period_start TEXT,
                    period_end TEXT,
                    is_natural INTEGER DEFAULT 0,
                    response_days INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS medications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    inositol INTEGER DEFAULT 0,
                    magnesium INTEGER DEFAULT 0,
                    k2 INTEGER DEFAULT 0,
                    progesterone INTEGER DEFAULT 0,
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(date)
                );

                CREATE TABLE IF NOT EXISTS body_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    datetime TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS anniversaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    month INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    is_lunar INTEGER DEFAULT 0,
                    recurring INTEGER DEFAULT 1,
                    year INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS kai_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    datetime TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    due_date TEXT,
                    done INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS med_streaks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplement TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    days INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS holidays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    holiday_type TEXT DEFAULT 'holiday',
                    UNIQUE(year, name, date)
                );
            """)
            conn.commit()
        finally:
            conn.close()

    # ========== 经期记录 ==========

    def add_period(self, **kwargs) -> int:
        conn = self._get_conn()
        try:
            fields = {k: v for k, v in kwargs.items() if v is not None}
            if 'progesterone_stop' in fields and 'period_start' in fields:
                try:
                    stop = datetime.strptime(fields['progesterone_stop'], '%Y-%m-%d')
                    start = datetime.strptime(fields['period_start'], '%Y-%m-%d')
                    fields['response_days'] = (start - stop).days
                except (ValueError, TypeError):
                    pass
            cols = ', '.join(fields.keys())
            placeholders = ', '.join(['?'] * len(fields))
            cursor = conn.execute(
                f"INSERT INTO periods ({cols}) VALUES ({placeholders})",
                list(fields.values())
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_period(self, period_id: int, **kwargs):
        conn = self._get_conn()
        try:
            fields = {k: v for k, v in kwargs.items() if v is not None}
            if 'progesterone_stop' in fields or 'period_start' in fields:
                row = conn.execute("SELECT * FROM periods WHERE id=?", (period_id,)).fetchone()
                if row:
                    stop_str = fields.get('progesterone_stop', row['progesterone_stop'])
                    start_str = fields.get('period_start', row['period_start'])
                    if stop_str and start_str:
                        try:
                            stop = datetime.strptime(stop_str, '%Y-%m-%d')
                            start = datetime.strptime(start_str, '%Y-%m-%d')
                            fields['response_days'] = (start - stop).days
                        except (ValueError, TypeError):
                            pass
            if fields:
                sets = ', '.join([f"{k}=?" for k in fields.keys()])
                conn.execute(f"UPDATE periods SET {sets} WHERE id=?",
                             list(fields.values()) + [period_id])
                conn.commit()
        finally:
            conn.close()

    def get_latest_period(self) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM periods ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_periods(self, limit: int = 10) -> list:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM periods ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ========== 用药打卡 ==========

    def record_medication(self, date: str, **kwargs):
        conn = self._get_conn()
        try:
            existing = conn.execute(
                "SELECT id FROM medications WHERE date=?", (date,)
            ).fetchone()
            if existing:
                fields = {k: v for k, v in kwargs.items() if v is not None}
                if fields:
                    sets = ', '.join([f"{k}=?" for k in fields.keys()])
                    conn.execute(f"UPDATE medications SET {sets} WHERE date=?",
                                 list(fields.values()) + [date])
            else:
                fields = {'date': date}
                fields.update({k: v for k, v in kwargs.items() if v is not None})
                cols = ', '.join(fields.keys())
                placeholders = ', '.join(['?'] * len(fields))
                conn.execute(
                    f"INSERT INTO medications ({cols}) VALUES ({placeholders})",
                    list(fields.values())
                )
            conn.commit()
        finally:
            conn.close()

    def get_medication(self, date: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM medications WHERE date=?", (date,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_medication_history(self, days: int = 7) -> list:
        conn = self._get_conn()
        try:
            start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT * FROM medications WHERE date >= ? ORDER BY date DESC",
                (start,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_med_missing_days(self) -> int:
        conn = self._get_conn()
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            row = conn.execute(
                "SELECT date FROM medications WHERE "
                "(inositol=1 OR magnesium=1 OR k2=1) "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if not row:
                return 999
            last_date = datetime.strptime(row['date'], '%Y-%m-%d')
            return (datetime.now() - last_date).days
        finally:
            conn.close()

    # ========== Streak计算 ==========

    def calculate_streak(self, supplement: str = 'all') -> dict:
        conn = self._get_conn()
        try:
            today = datetime.now().date()
            rows = conn.execute(
                "SELECT date, inositol, magnesium, k2 FROM medications "
                "ORDER BY date DESC"
            ).fetchall()

            current_streak = 0
            for row in rows:
                d = datetime.strptime(row['date'], '%Y-%m-%d').date()
                expected = today - timedelta(days=current_streak)
                if d != expected:
                    break
                if supplement == 'all':
                    if row['inositol'] and row['magnesium'] and row['k2']:
                        current_streak += 1
                    else:
                        break
                else:
                    if row[supplement]:
                        current_streak += 1
                    else:
                        break

            best = conn.execute(
                "SELECT * FROM med_streaks WHERE supplement=? ORDER BY days DESC LIMIT 1",
                (supplement,)
            ).fetchone()
            best_streak = dict(best) if best else {'days': 0, 'start_date': None, 'end_date': None}

            if current_streak > 0 and current_streak > best_streak['days']:
                start_date = (today - timedelta(days=current_streak - 1)).strftime('%Y-%m-%d')
                conn.execute(
                    "INSERT INTO med_streaks (supplement, start_date, end_date, days) "
                    "VALUES (?, ?, ?, ?)",
                    (supplement, start_date, today.strftime('%Y-%m-%d'), current_streak)
                )
                conn.commit()
                best_streak = {'days': current_streak, 'start_date': start_date,
                               'end_date': today.strftime('%Y-%m-%d')}

            return {
                'current': current_streak,
                'best_days': best_streak['days'],
                'best_start': best_streak.get('start_date'),
                'best_end': best_streak.get('end_date'),
            }
        finally:
            conn.close()

    # ========== 身体备注 ==========

    def add_body_note(self, content: str, tags: str = '', dt: str = None) -> int:
        conn = self._get_conn()
        try:
            if not dt:
                dt = datetime.now().strftime('%Y-%m-%d %H:%M')
            cursor = conn.execute(
                "INSERT INTO body_notes (datetime, content, tags) VALUES (?, ?, ?)",
                (dt, content, tags)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_body_notes(self, days: int = 7) -> list:
        conn = self._get_conn()
        try:
            start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT * FROM body_notes WHERE datetime >= ? ORDER BY datetime DESC",
                (start,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ========== 纪念日 ==========

    def add_anniversary(self, name: str, month: int, day: int,
                        is_lunar: int = 0, recurring: int = 1,
                        year: int = None, notes: str = None) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "INSERT INTO anniversaries (name, month, day, is_lunar, recurring, year, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, month, day, is_lunar, recurring, year, notes)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def delete_anniversary(self, anniversary_id: int):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM anniversaries WHERE id=?", (anniversary_id,))
            conn.commit()
        finally:
            conn.close()

    def update_anniversary(self, anniversary_id: int, **kwargs):
        conn = self._get_conn()
        try:
            fields = {k: v for k, v in kwargs.items() if v is not None}
            if fields:
                sets = ', '.join([f"{k}=?" for k in fields.keys()])
                conn.execute(f"UPDATE anniversaries SET {sets} WHERE id=?",
                             list(fields.values()) + [anniversary_id])
                conn.commit()
        finally:
            conn.close()

    def get_all_anniversaries(self) -> list:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM anniversaries ORDER BY month, day"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ========== Kai备注 ==========

    def add_kai_note(self, content: str, dt: str = None) -> int:
        conn = self._get_conn()
        try:
            if not dt:
                dt = datetime.now().strftime('%Y-%m-%d %H:%M')
            cursor = conn.execute(
                "INSERT INTO kai_notes (datetime, content) VALUES (?, ?)",
                (dt, content)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_kai_notes(self, limit: int = 20) -> list:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM kai_notes ORDER BY datetime DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ========== 待办 ==========

    def add_todo(self, content: str, due_date: str = None) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "INSERT INTO todos (content, due_date) VALUES (?, ?)",
                (content, due_date)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def complete_todo(self, todo_id: int):
        conn = self._get_conn()
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            conn.execute(
                "UPDATE todos SET done=1, completed_at=? WHERE id=?",
                (now, todo_id)
            )
            conn.commit()
        finally:
            conn.close()

    def delete_todo(self, todo_id: int):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM todos WHERE id=?", (todo_id,))
            conn.commit()
        finally:
            conn.close()

    def get_pending_todos(self) -> list:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM todos WHERE done=0 ORDER BY due_date ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_due_todos(self, date: str = None) -> list:
        conn = self._get_conn()
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT * FROM todos WHERE done=0 AND due_date <= ? ORDER BY due_date ASC",
                (date,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ========== 中国假日 ==========

    def add_holiday(self, year: int, name: str, date: str, holiday_type: str = 'holiday'):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO holidays (year, name, date, holiday_type) "
                "VALUES (?, ?, ?, ?)",
                (year, name, date, holiday_type)
            )
            conn.commit()
        finally:
            conn.close()

    def get_holidays(self, year: int = None) -> list:
        conn = self._get_conn()
        try:
            if year:
                rows = conn.execute(
                    "SELECT * FROM holidays WHERE year=? ORDER BY date", (year,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM holidays ORDER BY date"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_upcoming_holidays(self, days: int = 30) -> list:
        conn = self._get_conn()
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            end = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT * FROM holidays WHERE date BETWEEN ? AND ? AND holiday_type='holiday' "
                "ORDER BY date",
                (today, end)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ========== 趋势分析 ==========

    def get_period_trends(self) -> dict:
        conn = self._get_conn()
        try:
            periods = conn.execute(
                "SELECT * FROM periods ORDER BY id DESC LIMIT 12"
            ).fetchall()
            periods = [dict(r) for r in periods]

            response_days = [p['response_days'] for p in periods if p['response_days'] is not None]
            natural_count = sum(1 for p in periods if p['is_natural'])
            prog_days_list = []
            for p in periods:
                if p['progesterone_start'] and p['progesterone_stop']:
                    try:
                        start = datetime.strptime(p['progesterone_start'], '%Y-%m-%d')
                        stop = datetime.strptime(p['progesterone_stop'], '%Y-%m-%d')
                        prog_days_list.append((stop - start).days)
                    except (ValueError, TypeError):
                        pass

            return {
                'total_records': len(periods),
                'natural_periods': natural_count,
                'response_days_history': response_days,
                'avg_response_days': round(sum(response_days) / len(response_days), 1) if response_days else None,
                'progesterone_duration_history': prog_days_list,
                'avg_progesterone_days': round(sum(prog_days_list) / len(prog_days_list), 1) if prog_days_list else None,
            }
        finally:
            conn.close()

    # ========== 主动检查（定时任务用） ==========

    def check_daily(self, today_str: str = None) -> dict:
        if not today_str:
            today_str = datetime.now().strftime('%Y-%m-%d')
        today = datetime.strptime(today_str, '%Y-%m-%d')

        alerts = {
            'anniversaries': [],
            'holidays': [],
            'med_missing_days': 0,
            'due_todos': [],
            'progesterone_status': None,
        }

        # 纪念日检查（前3天+当天）
        annivs = self.get_all_anniversaries()
        for a in annivs:
            if a['is_lunar']:
                continue  # 农历在main.py里单独处理
            anniv_this_year = today.replace(month=a['month'], day=a['day'])
            diff = (anniv_this_year - today).days
            if 0 <= diff <= 3:
                alerts['anniversaries'].append({
                    'name': a['name'],
                    'date': anniv_this_year.strftime('%Y-%m-%d'),
                    'days_until': diff,
                })

        # 假日检查
        alerts['holidays'] = self.get_upcoming_holidays(days=7)

        # 用药缺失
        alerts['med_missing_days'] = self.get_med_missing_days()

        # 待办到期
        alerts['due_todos'] = self.get_due_todos(today_str)

        # 黄体酮状态
        latest = self.get_latest_period()
        if latest:
            if latest['progesterone_stop'] and not latest['period_start']:
                try:
                    stop = datetime.strptime(latest['progesterone_stop'], '%Y-%m-%d')
                    days_since_stop = (today - stop).days
                    alerts['progesterone_status'] = {
                        'status': 'waiting_period',
                        'days_since_stop': days_since_stop,
                    }
                except (ValueError, TypeError):
                    pass
            elif latest['progesterone_start'] and not latest['progesterone_stop']:
                alerts['progesterone_status'] = {
                    'status': 'taking_progesterone',
                    'start_date': latest['progesterone_start'],
                }

        return alerts
