# -*- coding: utf-8 -*-
"""Ядро учёта рабочего времени и выплат. ВЕРСИЯ 2.0.0.
Надмножество версии 1.1.3: сохранены штрафы и схема настроек received_*,
добавлены поля синхронизации version/sync_status."""
import os
import re
import json
import sqlite3
import datetime as dt
from dataclasses import dataclass, asdict

APP_NAME = "Табель 2.0"
DB_FILENAME = "timecard.db"

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг",
               "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_RU_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
             "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_RU_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                 "августа", "сентября", "октября", "ноября", "декабря"]

THEME = {
    "bg": "#E7EDF3", "surface": "#F4F8FC", "surface_alt": "#DEE7F0",
    "border": "#C3D2E0", "accent": "#5B9BD5", "accent_dark": "#417CB8",
    "accent_light": "#BBD6EE", "text": "#22313F", "text_muted": "#6B7C8C",
    "ok": "#4C9A6A", "warn": "#C87A3E", "danger": "#B5544B", "white": "#FFFFFF",
}

def parse_time(text):
    """'8'/'17' -> час ровно; '8:00'/'8.00'/'8,00'/'8;00'/'8 00'/'0800' -> 480;
    '17:15'/'17.15'/'17,15'/'17;15' -> 1035. None если пусто или мусор."""
    if text is None:
        return None
    s = str(text).strip()
    s = s.replace(",", ".").replace(";", ".").replace(" ", "").replace(".", ":")
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2:
            return None
        h_s, m_s = parts
        if not (h_s.isascii() and h_s.isdigit() and m_s.isascii() and m_s.isdigit()):
            return None
        if not (1 <= len(h_s) <= 2 and 1 <= len(m_s) <= 2):
            return None
        h, mi = int(h_s), int(m_s)
    elif s.isascii() and s.isdigit():
        if len(s) <= 2:
            h, mi = int(s), 0
        elif len(s) in (3, 4):
            h, mi = int(s[:-2]), int(s[-2:])
        else:
            return None
    else:
        return None
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h * 60 + mi

def parse_duration(text):
    """Длительность обеда: '30'/'45'/'90' -> минуты;
    '1:00'/'1.00'/'1,00'/'1;00'/'1 00' -> 60 минут."""
    if text is None:
        return 0
    s = str(text).strip()
    s = s.replace(",", ".").replace(";", ".").replace(" ", "").replace(".", ":")
    if not s:
        return 0
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2:
            return 0
        h_s, m_s = parts
        if not (h_s.isascii() and h_s.isdigit() and m_s.isascii() and m_s.isdigit()):
            return 0
        if not (1 <= len(h_s) <= 2 and 1 <= len(m_s) <= 2):
            return 0
        return int(h_s) * 60 + int(m_s)
    if s.isascii() and s.isdigit():
        if len(s) <= 3:
            return int(s)
        if len(s) == 4:
            return int(s[:-2]) * 60 + int(s[-2:])
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
    penalty_on: bool = False
    penalty: float = 0.0
    approved_at: str = ""
    version: int = 1
    sync_status: str = "local"

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
    def penalty_pay(self):
        if not self.penalty_on:
            return 0.0
        return float(self.penalty or 0)

    @property
    def total_pay(self):
        return self.day_pay + self.extra_pay + float(self.bonus or 0) - self.penalty_pay

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
        return asdict(self)

    @staticmethod
    def from_row(row):
        d = dict(row)
        d.pop("id", None)
        for k in ("lunch_on", "extra_on", "extra_use_fixed", "penalty_on"):
            d[k] = bool(d.get(k))
        d.setdefault("approved_at", "")
        d.setdefault("version", 1)
        d.setdefault("sync_status", "local")
        return DayEntry(**d)

def week_start(d):
    return d - dt.timedelta(days=d.weekday())

def week_range(d):
    ws = week_start(d)
    return ws, ws + dt.timedelta(days=6)

def week_title(d):
    a, b = week_range(d)
    if a.month == b.month:
        return "%d–%d %s %d" % (a.day, b.day, MONTHS_RU_GEN[a.month - 1], a.year)
    return "%d %s – %d %s %d" % (a.day, MONTHS_RU_GEN[a.month - 1],
                                  b.day, MONTHS_RU_GEN[b.month - 1], b.year)

def month_title(d):
    return "%s %d" % (MONTHS_RU[d.month - 1], d.year)

def month_range(d):
    first = d.replace(day=1)
    if d.month == 12:
        last = d.replace(day=31)
    else:
        last = d.replace(month=d.month + 1, day=1) - dt.timedelta(days=1)
    return first, last

class Totals:
    def __init__(self, entries):
        self.days = [e for e in entries if not e.is_empty]
        self.work_min = sum(e.work_min for e in self.days)
        self.extra_min = sum(e.extra_min for e in self.days)
        self.total_min = self.work_min + self.extra_min
        self.day_pay = sum(e.day_pay for e in self.days)
        self.extra_pay = sum(e.extra_pay for e in self.days)
        self.bonus = sum(float(e.bonus or 0) for e in self.days)
        self.penalty = sum(e.penalty_pay for e in self.days)
        self.total_pay = self.day_pay + self.extra_pay + self.bonus - self.penalty
        self.worked_days = len(self.days)

SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    start INTEGER, end INTEGER,
    lunch_on INTEGER DEFAULT 0, lunch_min INTEGER DEFAULT 0,
    works TEXT DEFAULT '',
    extra_on INTEGER DEFAULT 0, extra_start INTEGER, extra_end INTEGER,
    extra_works TEXT DEFAULT '', extra_rate REAL DEFAULT 250,
    extra_fixed REAL DEFAULT 0, extra_use_fixed INTEGER DEFAULT 0,
    bonus REAL DEFAULT 0, rate REAL DEFAULT 250, note TEXT DEFAULT '',
    penalty_on INTEGER DEFAULT 0, penalty REAL DEFAULT 0,
    approved_at TEXT DEFAULT '', version INTEGER DEFAULT 1,
    sync_status TEXT DEFAULT 'local'
);
CREATE INDEX IF NOT EXISTS idx_days_date ON days(date);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_SETTINGS = {
    "rate": "250", "extra_rate": "250",
    "default_start": "8:00", "default_end": "17:00", "default_lunch": "60",
    "employee": "", "organization": "", "rounding": "ruble",
    "secret_key": "", "employee_id": "", "employee_token": "",
}

_MIGRATIONS = [
    ("penalty_on", "INTEGER DEFAULT 0"),
    ("penalty", "REAL DEFAULT 0"),
    ("approved_at", "TEXT DEFAULT ''"),
    ("version", "INTEGER DEFAULT 1"),
    ("sync_status", "TEXT DEFAULT 'local'"),
]

def default_data_dir():
    android = os.environ.get("ANDROID_APP_PATH") or os.environ.get("ANDROID_ARGUMENT")
    if android:
        return os.environ.get("ANDROID_PRIVATE") or android
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
        # check_same_thread=False: на Android callback опроса очереди приходит
        # из сетевого потока и обязан иметь возможность писать в БД
        # (mark_approved). Без флага sqlite3 бросает ProgrammingError,
        # который тихо глотается обёрткой потока — одобрение терялось.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(days)")]
        for name, ddl in _MIGRATIONS:
            if name not in cols:
                self.conn.execute("ALTER TABLE days ADD COLUMN %s %s" % (name, ddl))
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
        return DayEntry(date=date, rate=self.get_float("rate", 250),
                        extra_rate=self.get_float("extra_rate", 250))

    def save_day(self, e):
        if e.is_empty:
            self.conn.execute("DELETE FROM days WHERE date=?", (e.date,))
            self.conn.commit()
            return
        self.conn.execute("""
            INSERT INTO days(date,start,end,lunch_on,lunch_min,works,extra_on,
                extra_start,extra_end,extra_works,extra_rate,extra_fixed,
                extra_use_fixed,bonus,rate,note,penalty_on,penalty,
                approved_at,version,sync_status)
            VALUES(:date,:start,:end,:lunch_on,:lunch_min,:works,:extra_on,
                :extra_start,:extra_end,:extra_works,:extra_rate,:extra_fixed,
                :extra_use_fixed,:bonus,:rate,:note,:penalty_on,:penalty,
                :approved_at,:version,:sync_status)
            ON CONFLICT(date) DO UPDATE SET
                start=excluded.start, end=excluded.end,
                lunch_on=excluded.lunch_on, lunch_min=excluded.lunch_min,
                works=excluded.works, extra_on=excluded.extra_on,
                extra_start=excluded.extra_start, extra_end=excluded.extra_end,
                extra_works=excluded.extra_works, extra_rate=excluded.extra_rate,
                extra_fixed=excluded.extra_fixed,
                extra_use_fixed=excluded.extra_use_fixed, bonus=excluded.bonus,
                rate=excluded.rate, note=excluded.note,
                penalty_on=excluded.penalty_on, penalty=excluded.penalty,
                approved_at=excluded.approved_at, version=excluded.version,
                sync_status=excluded.sync_status
        """, {**e.to_dict(),
              "lunch_on": int(e.lunch_on), "extra_on": int(e.extra_on),
              "extra_use_fixed": int(e.extra_use_fixed),
              "penalty_on": int(e.penalty_on)})
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
            # Идентификация устройства не переносится из копии: иначе
            # восстановление резервной копии, сделанной до регистрации,
            # стирает employee_id/employee_token и разлогинивает устройство.
            if k in ("employee_id", "employee_token", "secret_key"):
                continue
            self.set(k, v)
        n = 0
        for row in data.get("days", []):
            row.pop("id", None)
            self.save_day(DayEntry.from_row(row))
            n += 1
        return n

    # --- закрытые недели: совместимо с backup_restore.py (ключи received_*) ---
    @staticmethod
    def _monday(anchor):
        if not isinstance(anchor, dt.date):
            anchor = dt.date.fromisoformat(anchor)
        return week_start(anchor).isoformat()

    def week_received(self, anchor):
        return self.get("received_week_" + self._monday(anchor), "0") == "1"

    def received_on(self, anchor):
        return self.get("received_on_" + self._monday(anchor), "")

    def set_received(self, anchor, iso_date):
        m = self._monday(anchor)
        self.set("received_week_" + m, "1")
        self.set("received_on_" + m, iso_date)

    # --- одобрение дней ---
    def is_approved(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        r = self.conn.execute("SELECT approved_at FROM days WHERE date=?", (date,)).fetchone()
        return bool(r and r["approved_at"])

    def mark_approved(self, date, approved_at=None):
        if isinstance(date, dt.date):
            date = date.isoformat()
        if approved_at is None:
            approved_at = dt.datetime.now().isoformat()
        self.conn.execute(
            "UPDATE days SET approved_at=?, sync_status='synced' WHERE date=?",
            (approved_at, date))
        self.conn.commit()

    def week_complete(self, anchor):
        filled = [e for e in self.week_days(anchor) if not e.is_empty]
        if not filled:
            return False
        return all(self.is_approved(e.date) for e in filled)

    # --- версии для синхронизации ---
    def get_day_version(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        r = self.conn.execute("SELECT version FROM days WHERE date=?", (date,)).fetchone()
        return r["version"] if r else 1

    def increment_day_version(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        r = self.conn.execute("SELECT version FROM days WHERE date=?", (date,)).fetchone()
        new_v = (r["version"] + 1) if r else 1
        if r:
            self.conn.execute("UPDATE days SET version=? WHERE date=?", (new_v, date))
            self.conn.commit()
        return new_v

    def get_week_version(self, anchor):
        try:
            return int(self.get("payver_" + self._monday(anchor), "0") or 0)
        except (TypeError, ValueError):
            return 0

    def increment_week_version(self, anchor):
        v = self.get_week_version(anchor) + 1
        self.set("payver_" + self._monday(anchor), str(v))
        return v

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
