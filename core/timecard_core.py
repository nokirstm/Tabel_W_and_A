# -*- coding: utf-8 -*-
"""
Ядро учёта рабочего времени и выплат.
Общий модуль для Windows (.exe) и Android (.apk) — не зависит от GUI.
Только стандартная библиотека Python.
ВЕРСИЯ 2.0.0 - Добавлена поддержка синхронизации
"""
import os
import re
import json
import sqlite3
import datetime as dt
from dataclasses import dataclass, field, asdict

APP_NAME = "Табель 2.0"
DB_FILENAME = "timecard.db"

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг",
               "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_RU_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
             "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_RU_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                 "августа", "сентября", "октября", "ноября", "декабря"]

# ----------------------------------------------------------------------------
# ЦВЕТОВАЯ СХЕМА
# ----------------------------------------------------------------------------
THEME = {
    "bg": "#E7EDF3",
    "surface": "#F4F8FC",
    "surface_alt": "#DEE7F0",
    "border": "#C3D2E0",
    "accent": "#5B9BD5",
    "accent_dark": "#417CB8",
    "accent_light": "#BBD6EE",
    "text": "#22313F",
    "text_muted": "#6B7C8C",
    "ok": "#4C9A6A",
    "warn": "#C87A3E",
    "danger": "#B5544B",
    "white": "#FFFFFF",
}

# ----------------------------------------------------------------------------
# Разбор и формат времени
# ----------------------------------------------------------------------------
def parse_time(text):
    if text is None:
        return None
    s = str(text).strip().replace(",", ".").replace(" ", "")
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{1,2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"\d{1,2}", s):
        h, mi = int(s), 0
    elif re.fullmatch(r"\d{3,4}", s):
        h, mi = int(s[:-2]), int(s[-2:])
    else:
        return None
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h * 60 + mi

def parse_duration(text):
    if text is None:
        return 0
    s = str(text).strip().replace(",", ".").replace(" ", "")
    if not s:
        return 0
    m = re.fullmatch(r"(\d{1,2}):(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    if re.fullmatch(r"\d{1,3}", s):
        return int(s)
    return 0

def fmt_time(minutes):
    if minutes is None:
        return ""
    minutes %= 24 * 60
    return "%02d:%02d" % (minutes // 60, minutes % 60)

def fmt_hm(minutes):
    minutes = int(minutes or 0)
    return "%d ч %02d мин" % (minutes // 60, minutes % 60)

def fmt_hm_short(minutes):
    minutes = int(minutes or 0)
    return "%d.%02d" % (minutes // 60, minutes % 60)

def fmt_money(value):
    v = round(float(value or 0))
    return "{:,}".format(v).replace(",", " ") + " \u20bd"

def span_minutes(start, end):
    if start is None or end is None:
        return 0
    d = end - start
    if d < 0:
        d += 24 * 60
    return d

# ----------------------------------------------------------------------------
# Модель дня (РАСШИРЕННАЯ для синхронизации)
# ----------------------------------------------------------------------------
@dataclass
class DayEntry:
    date: str = ""
    start: int = None
    end: int = None
    lunch_on: bool = False
    lunch_min: int = 0
    works: str = ""
    extra_on: bool = False
    extra_start: int = None
    extra_end: int = None
    extra_works: str = ""
    extra_rate: float = 250.0
    extra_fixed: float = 0.0
    extra_use_fixed: bool = False
    bonus: float = 0.0
    rate: float = 250.0
    note: str = ""
    # --- НОВЫЕ ПОЛЯ ДЛЯ СИНХРОНИЗАЦИИ ---
    approved_at: str = ""  # ISO datetime когда одобрен
    version: int = 1  # версия для контроля конфликтов
    sync_status: str = "local"  # local | synced | conflict
    
    @property
    def work_min(self):
        total = span_minutes(self.start, self.end)
        if self.lunch_on:
            total -= max(0, int(self.lunch_min or 0))
        return max(0, total)
    
    @property
    def extra_min(self):
        if not self.extra_on:
            return 0
        return span_minutes(self.extra_start, self.extra_end)
    
    @property
    def total_min(self):
        return self.work_min + self.extra_min
    
    @property
    def day_pay(self):
        return self.work_min / 60.0 * float(self.rate or 0)
    
    @property
    def extra_pay(self):
        if not self.extra_on:
            return 0.0
        if self.extra_use_fixed:
            return float(self.extra_fixed or 0)
        return self.extra_min / 60.0 * float(self.extra_rate or 0)
    
    @property
    def total_pay(self):
        return self.day_pay + self.extra_pay + float(self.bonus or 0)
    
    @property
    def date_obj(self):
        return dt.date.fromisoformat(self.date)
    
    @property
    def weekday_name(self):
        return WEEKDAYS_RU[self.date_obj.weekday()]
    
    @property
    def is_empty(self):
        return (self.start is None and self.end is None
                and not self.works.strip() and not self.extra_on
                and not float(self.bonus or 0))
    
    def to_dict(self):
        d = asdict(self)
        # Убираем поля синхронизации из payload для сервера
        d.pop('approved_at', None)
        d.pop('version', None)
        d.pop('sync_status', None)
        return d
    
    @staticmethod
    def from_row(row):
        d = dict(row)
        d.pop("id", None)
        d["lunch_on"] = bool(d.get("lunch_on"))
        d["extra_on"] = bool(d.get("extra_on"))
        d["extra_use_fixed"] = bool(d.get("extra_use_fixed"))
        # Обработка новых полей с значениями по умолчанию
        d["approved_at"] = d.get("approved_at") or ""
        d["version"] = d.get("version") or 1
        d["sync_status"] = d.get("sync_status") or "local"
        return DayEntry(**d)

# ----------------------------------------------------------------------------
# Периоды
# ----------------------------------------------------------------------------
def week_start(d):
    return d - dt.timedelta(days=d.weekday())

def week_range(d):
    ws = week_start(d)
    return ws, ws + dt.timedelta(days=6)

def week_title(d):
    a, b = week_range(d)
    if a.month == b.month:
        return "%d–%d %s %d" % (a.day, b.day, MONTHS_RU_GEN[a.month-1], a.year)
    return "%d %s – %d %s %d" % (a.day, MONTHS_RU_GEN[a.month-1],
                                  b.day, MONTHS_RU_GEN[b.month-1], b.year)

def month_title(d):
    return "%s %d" % (MONTHS_RU[d.month-1], d.year)

def month_range(d):
    first = d.replace(day=1)
    if d.month == 12:
        last = d.replace(day=31)
    else:
        last = d.replace(month=d.month+1, day=1) - dt.timedelta(days=1)
    return first, last

# ----------------------------------------------------------------------------
# Итоги
# ----------------------------------------------------------------------------
class Totals:
    def __init__(self, entries):
        self.days = [e for e in entries if not e.is_empty]
        self.work_min = sum(e.work_min for e in self.days)
        self.extra_min = sum(e.extra_min for e in self.days)
        self.total_min = self.work_min + self.extra_min
        self.day_pay = sum(e.day_pay for e in self.days)
        self.extra_pay = sum(e.extra_pay for e in self.days)
        self.bonus = sum(float(e.bonus or 0) for e in self.days)
        self.penalty = 0.0  # Для совместимости
        self.total_pay = self.day_pay + self.extra_pay + self.bonus
        self.worked_days = len(self.days)

# ----------------------------------------------------------------------------
# Хранилище (SQLite) - РАСШИРЕННАЯ ВЕРСИЯ
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    start INTEGER,
    end INTEGER,
    lunch_on INTEGER DEFAULT 0,
    lunch_min INTEGER DEFAULT 0,
    works TEXT DEFAULT '',
    extra_on INTEGER DEFAULT 0,
    extra_start INTEGER,
    extra_end INTEGER,
    extra_works TEXT DEFAULT '',
    extra_rate REAL DEFAULT 250,
    extra_fixed REAL DEFAULT 0,
    extra_use_fixed INTEGER DEFAULT 0,
    bonus REAL DEFAULT 0,
    rate REAL DEFAULT 250,
    note TEXT DEFAULT '',
    approved_at TEXT DEFAULT '',
    version INTEGER DEFAULT 1,
    sync_status TEXT DEFAULT 'local'
);
CREATE INDEX IF NOT EXISTS idx_days_date ON days(date);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS payment_state (
    week_id TEXT PRIMARY KEY,
    payment_date TEXT DEFAULT '',
    payment_confirmed INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1
);
"""

DEFAULT_SETTINGS = {
    "rate": "250",
    "extra_rate": "250",
    "default_start": "8:00",
    "default_end": "17:00",
    "default_lunch": "60",
    "employee": "",
    "organization": "",
    "rounding": "ruble",
    # --- НОВЫЕ НАСТРОЙКИ ДЛЯ СИНХРОНИЗАЦИИ ---
    "employee_id": "",
    "employee_token": "",
    "device_id": "",
    "last_sync": "",
    "sync_enabled": "0"
}

def default_data_dir():
    android = os.environ.get("ANDROID_APP_PATH") or os.environ.get("ANDROID_ARGUMENT")
    if android:
        base = os.environ.get("ANDROID_PRIVATE") or android
        return base
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = os.path.join(appdata, "TabelUcheta")
    else:
        p = os.path.join(os.path.expanduser("~"), ".tabel_ucheta")
    os.makedirs(p, exist_ok=True)
    return p

class Storage:
    def __init__(self, path=None):
        self.path = path or os.path.join(default_data_dir(), DB_FILENAME)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        
        # Миграция: добавляем новые колонки если их нет
        cursor = self.conn.execute("PRAGMA table_info(days)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'approved_at' not in columns:
            self.conn.execute("ALTER TABLE days ADD COLUMN approved_at TEXT DEFAULT ''")
        if 'version' not in columns:
            self.conn.execute("ALTER TABLE days ADD COLUMN version INTEGER DEFAULT 1")
        if 'sync_status' not in columns:
            self.conn.execute("ALTER TABLE days ADD COLUMN sync_status TEXT DEFAULT 'local'")
        self.conn.commit()
        
        for k, v in DEFAULT_SETTINGS.items():
            self.conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        self.conn.commit()
    
    def get(self, key, default=None):
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else (default if default is not None
                                      else DEFAULT_SETTINGS.get(key, ""))
    
    def get_float(self, key, default=0.0):
        try:
            return float(str(self.get(key)).replace(",", "."))
        except (TypeError, ValueError):
            return default
    
    def set(self, key, value):
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()
    
    def load_day(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        r = self.conn.execute("SELECT * FROM days WHERE date=?", (date,)).fetchone()
        if r:
            return DayEntry.from_row(r)
        return DayEntry(date=date,
                       rate=self.get_float("rate", 250),
                       extra_rate=self.get_float("extra_rate", 250))
    
    def save_day(self, e: DayEntry):
        if e.is_empty:
            self.conn.execute("DELETE FROM days WHERE date=?", (e.date,))
            self.conn.commit()
            return
        
        self.conn.execute("""
            INSERT INTO days(date,start,end,lunch_on,lunch_min,works,extra_on,
                           extra_start,extra_end,extra_works,extra_rate,
                           extra_fixed,extra_use_fixed,bonus,rate,note,
                           approved_at,version,sync_status)
            VALUES(:date,:start,:end,:lunch_on,:lunch_min,:works,:extra_on,
                   :extra_start,:extra_end,:extra_works,:extra_rate,
                   :extra_fixed,:extra_use_fixed,:bonus,:rate,:note,
                   :approved_at,:version,:sync_status)
            ON CONFLICT(date) DO UPDATE SET
                start=excluded.start, end=excluded.end, lunch_on=excluded.lunch_on,
                lunch_min=excluded.lunch_min, works=excluded.works,
                extra_on=excluded.extra_on, extra_start=excluded.extra_start,
                extra_end=excluded.extra_end, extra_works=excluded.extra_works,
                extra_rate=excluded.extra_rate, extra_fixed=excluded.extra_fixed,
                extra_use_fixed=excluded.extra_use_fixed, bonus=excluded.bonus,
                rate=excluded.rate, note=excluded.note,
                approved_at=excluded.approved_at, version=excluded.version,
                sync_status=excluded.sync_status
        """, {**e.to_dict(),
              "lunch_on": int(e.lunch_on),
              "extra_on": int(e.extra_on),
              "extra_use_fixed": int(e.extra_use_fixed),
              "approved_at": e.approved_at,
              "version": e.version,
              "sync_status": e.sync_status})
        self.conn.commit()
    
    def delete_day(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        self.conn.execute("DELETE FROM days WHERE date=?", (date,))
        self.conn.commit()
    
    def range_days(self, d1, d2):
        rows = self.conn.execute(
            "SELECT * FROM days WHERE date BETWEEN ? AND ? ORDER BY date",
            (d1.isoformat(), d2.isoformat())).fetchall()
        saved = {r["date"]: DayEntry.from_row(r) for r in rows}
        out, cur = [], d1
        while cur <= d2:
            out.append(saved.get(cur.isoformat(),
                                DayEntry(date=cur.isoformat(),
                                        rate=self.get_float("rate", 250),
                                        extra_rate=self.get_float("extra_rate", 250))))
            cur += dt.timedelta(days=1)
        return out
    
    def week_days(self, anchor):
        a, b = week_range(anchor)
        return self.range_days(a, b)
    
    def month_days(self, anchor):
        a, b = month_range(anchor)
        return self.range_days(a, b)
    
    def filled_months(self):
        rows = self.conn.execute(
            "SELECT DISTINCT substr(date,1,7) m FROM days ORDER BY m DESC").fetchall()
        return [r["m"] for r in rows]
    
    def filled_weeks(self):
        rows = self.conn.execute("SELECT DISTINCT date FROM days").fetchall()
        ws = {week_start(dt.date.fromisoformat(r["date"])) for r in rows}
        return sorted(ws, reverse=True)
    
       def export_json(self, path):
        rows = self.conn.execute("SELECT * FROM days ORDER BY date").fetchall()
        settings = {}
        for r in self.conn.execute("SELECT key, value FROM settings"):
            key = r["key"]
            if key in DEFAULT_SETTINGS or key.startswith(
                    ("received_week_", "received_on_")):
                settings[key] = r["value"]
        data = {
            "app": APP_NAME,
            "format_version": 1,
            "exported": dt.datetime.now().isoformat(timespec="seconds"),
            "settings": settings,
            "days": [dict(r) for r in rows],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path
    
    def import_json(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in (data.get("settings") or {}).items():
            self.set(k, v)
        n = 0
        for row in data.get("days", []):
            row.pop("id", None)
            self.save_day(DayEntry(**{**row,
                                     "lunch_on": bool(row.get("lunch_on")),
                                     "extra_on": bool(row.get("extra_on")),
                                     "extra_use_fixed": bool(row.get("extra_use_fixed")),
                                     "approved_at": row.get("approved_at", ""),
                                     "version": row.get("version", 1),
                                     "sync_status": row.get("sync_status", "local")}))
            n += 1
        return n
    
    # === НОВЫЕ МЕТОДЫ ДЛЯ СИНХРОНИЗАЦИИ ===
    
    def get_day_version(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        r = self.conn.execute("SELECT version FROM days WHERE date=?", (date,)).fetchone()
        return r["version"] if r else 1
    
    def increment_day_version(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        # Инкрементируем только если запись существует
        r = self.conn.execute("SELECT version FROM days WHERE date=?", (date,)).fetchone()
        if r:
            new_version = r["version"] + 1
            self.conn.execute("UPDATE days SET version=? WHERE date=?", (new_version, date))
            self.conn.commit()
            return new_version
        return 1
    
    def mark_approved(self, date, approved_at=None):
        if isinstance(date, dt.date):
            date = date.isoformat()
        if approved_at is None:
            approved_at = dt.datetime.now().isoformat()
        self.conn.execute("UPDATE days SET approved_at=?, sync_status='synced' WHERE date=?", 
                         (approved_at, date))
        self.conn.commit()
    
    def is_approved(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        r = self.conn.execute("SELECT approved_at FROM days WHERE date=?", (date,)).fetchone()
        return bool(r and r["approved_at"])
    
    def week_complete(self, anchor):
        days = self.week_days(anchor)
        filled = [e for e in days if not e.is_empty]
        if not filled:
            return False
        return all(self.is_approved(e.date) for e in filled)
    
    # === МЕТОДЫ ДЛЯ ВЫПЛАТ ===
    
    def get_payment_state(self, week_id):
        if isinstance(week_id, dt.date):
            week_id = week_start(week_id).isoformat()
        r = self.conn.execute("SELECT * FROM payment_state WHERE week_id=?", (week_id,)).fetchone()
        if r:
            return {
                'week_id': r['week_id'],
                'payment_date': r['payment_date'],
                'payment_confirmed': bool(r['payment_confirmed']),
                'version': r['version']
            }
        return None
    
    def set_payment_state(self, week_id, payment_date, payment_confirmed, version):
        if isinstance(week_id, dt.date):
            week_id = week_start(week_id).isoformat()
        self.conn.execute("""
            INSERT INTO payment_state(week_id, payment_date, payment_confirmed, version)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(week_id) DO UPDATE SET
                payment_date=excluded.payment_date,
                payment_confirmed=excluded.payment_confirmed,
                version=excluded.version
        """, (week_id, payment_date, int(payment_confirmed), version))
        self.conn.commit()
    
    def week_received(self, anchor):
        state = self.get_payment_state(anchor)
        return state and state['payment_confirmed'] if state else False
    
    def received_on(self, anchor):
        state = self.get_payment_state(anchor)
        return state['payment_date'] if state else ""
    
    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
