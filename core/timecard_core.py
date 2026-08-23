# -*- coding: utf-8 -*-
"""
Ядро учёта рабочего времени и выплат.
Общий модуль для Windows (.exe) и Android (.apk) — не зависит от GUI.
Только стандартная библиотека Python.
"""

import os
import re
import json
import sqlite3
import datetime as dt
from dataclasses import dataclass, field, asdict

APP_NAME = "Табель"
DB_FILENAME = "timecard.db"

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг",
               "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_RU_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
             "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_RU_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                 "августа", "сентября", "октября", "ноября", "декабря"]

# ----------------------------------------------------------------------------
# ЦВЕТОВАЯ СХЕМА — единая для Windows и Android
# «светло-серый с оттенком голубого неба»
# ----------------------------------------------------------------------------
THEME = {
    "bg":            "#E7EDF3",   # фон окна — светло-серый с голубым подтоном
    "surface":       "#F4F8FC",   # карточки/панели
    "surface_alt":   "#DEE7F0",   # чередование строк, шапки
    "border":        "#C3D2E0",
    "accent":        "#5B9BD5",   # небесно-голубой — кнопки, акценты
    "accent_dark":   "#417CB8",
    "accent_light":  "#BBD6EE",
    "text":          "#22313F",
    "text_muted":    "#6B7C8C",
    "ok":            "#4C9A6A",
    "warn":          "#C87A3E",
    "danger":        "#B5544B",
    "white":         "#FFFFFF",
}


# ----------------------------------------------------------------------------
# Разбор и формат времени
# ----------------------------------------------------------------------------
def parse_time(text):
    """'8' -> 480, '8:30' / '8.30' / '8 30' / '0830' -> 510. None если пусто/мусор."""
    if text is None:
        return None
    s = str(text).strip().replace(",", ".").replace(" ", "")
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})[:.\-](\d{1,2})", s)
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
    """Длительность обеда: '30' -> 30 мин, '1:00'/'1.00' -> 60 мин."""
    if text is None:
        return 0
    s = str(text).strip().replace(",", ".").replace(" ", "")
    if not s:
        return 0
    m = re.fullmatch(r"(\d{1,2})[:.\-](\d{1,2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    if re.fullmatch(r"\d{1,3}", s):
        return int(s)
    return 0


def fmt_time(minutes):
    """480 -> '08:00'"""
    if minutes is None:
        return ""
    minutes %= 24 * 60
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def fmt_hm(minutes):
    """567 -> '9 ч 27 мин'"""
    minutes = int(minutes or 0)
    return "%d ч %02d мин" % (minutes // 60, minutes % 60)


def fmt_hm_short(minutes):
    """567 -> '9.27' — как в бумажной ведомости"""
    minutes = int(minutes or 0)
    return "%d.%02d" % (minutes // 60, minutes % 60)


def fmt_money(value):
    """2333.0 -> '2 333 ₽'"""
    v = round(float(value or 0))
    return "{:,}".format(v).replace(",", " ") + " \u20bd"


def span_minutes(start, end):
    """Минуты между началом и концом, с переходом через полночь."""
    if start is None or end is None:
        return 0
    d = end - start
    if d < 0:
        d += 24 * 60
    return d


# ----------------------------------------------------------------------------
# Модель дня
# ----------------------------------------------------------------------------
@dataclass
class DayEntry:
    date: str = ""                    # 'YYYY-MM-DD'
    start: int = None                 # минуты от полуночи
    end: int = None
    lunch_on: bool = False
    lunch_min: int = 0
    works: str = ""                   # объём и качество произведённых работ
    extra_on: bool = False
    extra_start: int = None
    extra_end: int = None
    extra_works: str = ""
    extra_rate: float = 250.0         # своя ставка для доп. работ
    extra_fixed: float = 0.0          # фиксированная сумма вместо расчёта по часам
    extra_use_fixed: bool = False
    bonus: float = 0.0                # премия — разовая сумма вручную
    rate: float = 250.0               # ставка за час основной работы
    note: str = ""

    # ---- расчёты ----
    @property
    def work_min(self):
        """Чистое рабочее время основной смены (за вычетом обеда)."""
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

    # ---- служебное ----
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
        d["lunch_on"] = bool(d.get("lunch_on"))
        d["extra_on"] = bool(d.get("extra_on"))
        d["extra_use_fixed"] = bool(d.get("extra_use_fixed"))
        return DayEntry(**d)


# ----------------------------------------------------------------------------
# Периоды
# ----------------------------------------------------------------------------
def week_start(d):
    """Понедельник недели, в которую попадает дата d."""
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
        self.total_pay = self.day_pay + self.extra_pay + self.bonus
        self.worked_days = len(self.days)


# ----------------------------------------------------------------------------
# Хранилище (SQLite) — история недель и месяцев
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT UNIQUE NOT NULL,
    start           INTEGER,
    end             INTEGER,
    lunch_on        INTEGER DEFAULT 0,
    lunch_min       INTEGER DEFAULT 0,
    works           TEXT DEFAULT '',
    extra_on        INTEGER DEFAULT 0,
    extra_start     INTEGER,
    extra_end       INTEGER,
    extra_works     TEXT DEFAULT '',
    extra_rate      REAL DEFAULT 250,
    extra_fixed     REAL DEFAULT 0,
    extra_use_fixed INTEGER DEFAULT 0,
    bonus           REAL DEFAULT 0,
    rate            REAL DEFAULT 250,
    note            TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_days_date ON days(date);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
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
    "rounding": "ruble",   # ruble | kopeck | ten
}


def default_data_dir():
    """Каталог данных: на Android — рядом с приложением, на Windows — %APPDATA%."""
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
        for k, v in DEFAULT_SETTINGS.items():
            self.conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        self.conn.commit()

    # -- настройки --
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

    # -- дни --
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
                             extra_fixed,extra_use_fixed,bonus,rate,note)
            VALUES(:date,:start,:end,:lunch_on,:lunch_min,:works,:extra_on,
                   :extra_start,:extra_end,:extra_works,:extra_rate,
                   :extra_fixed,:extra_use_fixed,:bonus,:rate,:note)
            ON CONFLICT(date) DO UPDATE SET
              start=excluded.start, end=excluded.end, lunch_on=excluded.lunch_on,
              lunch_min=excluded.lunch_min, works=excluded.works,
              extra_on=excluded.extra_on, extra_start=excluded.extra_start,
              extra_end=excluded.extra_end, extra_works=excluded.extra_works,
              extra_rate=excluded.extra_rate, extra_fixed=excluded.extra_fixed,
              extra_use_fixed=excluded.extra_use_fixed, bonus=excluded.bonus,
              rate=excluded.rate, note=excluded.note
        """, {**e.to_dict(),
              "lunch_on": int(e.lunch_on),
              "extra_on": int(e.extra_on),
              "extra_use_fixed": int(e.extra_use_fixed)})
        self.conn.commit()

    def delete_day(self, date):
        if isinstance(date, dt.date):
            date = date.isoformat()
        self.conn.execute("DELETE FROM days WHERE date=?", (date,))
        self.conn.commit()

    def range_days(self, d1, d2):
        """Все календарные дни периода (пустые — заглушками), отсортированы."""
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
        """Список понедельников, где есть записи (свежие сверху)."""
        rows = self.conn.execute("SELECT DISTINCT date FROM days").fetchall()
        ws = {week_start(dt.date.fromisoformat(r["date"])) for r in rows}
        return sorted(ws, reverse=True)

    # -- резервная копия --
    def export_json(self, path):
        rows = self.conn.execute("SELECT * FROM days ORDER BY date").fetchall()
        data = {
            "app": APP_NAME,
            "exported": dt.datetime.now().isoformat(timespec="seconds"),
            "settings": {k: self.get(k) for k in DEFAULT_SETTINGS},
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
                                      "extra_use_fixed": bool(row.get("extra_use_fixed"))}))
            n += 1
        return n

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
