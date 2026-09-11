# -*- coding: utf-8 -*-
"""Android-only local data model for Tabel.

This module intentionally does not alter the Windows core.  A fresh test APK
uses a fresh SQLite database, while SQLite itself keeps entries between starts.
The approval/payment fields are also the local contract for the later GAS sync.
"""
import os, re, json, sqlite3, datetime as dt
from dataclasses import dataclass, asdict

DB_FILENAME = "timecard.db"
WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_RU_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_RU_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
THEME = {"bg":"#E7EDF3", "surface":"#F4F8FC", "surface_alt":"#DEE7F0", "border":"#C3D2E0", "accent":"#5B9BD5", "accent_dark":"#417CB8", "accent_light":"#BBD6EE", "text":"#22313F", "text_muted":"#6B7C8C", "ok":"#4C9A6A", "warn":"#C87A3E", "danger":"#B5544B", "white":"#FFFFFF"}

def parse_time(text):
    if text is None or not str(text).strip(): return None
    s = str(text).strip().lower().replace('.', ':').replace(' ', ':')
    if re.fullmatch(r'\d{3,4}', s):
        s = s[:-2] + ':' + s[-2:]
    try:
        if ':' in s:
            h, m = s.split(':', 1); h, m = int(h), int(m)
        else: h, m = int(s), 0
        if 0 <= h <= 23 and 0 <= m <= 59: return h * 60 + m
    except (TypeError, ValueError): pass
    return None

def parse_duration(text):
    try: return max(0, int(float(str(text).replace(',', '.').strip())))
    except (TypeError, ValueError): return 0

def fmt_time(minutes):
    return '' if minutes is None else '%02d:%02d' % (int(minutes)//60, int(minutes)%60)

def fmt_hm(minutes):
    minutes = int(minutes or 0); return '%d ч %02d мин' % (minutes//60, minutes%60)

def fmt_hm_short(minutes):
    minutes = int(minutes or 0); return '%d:%02d' % (minutes//60, minutes%60)

def fmt_money(value):
    value = float(value or 0); return ('%.2f' % value).replace('.', ',') + ' ₽'

def span_minutes(start, end):
    if start is None or end is None: return 0
    return max(0, int(end) - int(start))

@dataclass
class DayEntry:
    date: str = ''
    start: int = None; end: int = None
    lunch_on: bool = False; lunch_min: int = 0
    works: str = ''
    extra_on: bool = False; extra_start: int = None; extra_end: int = None
    extra_works: str = ''; extra_rate: float = 250.0; extra_fixed: float = 0.0; extra_use_fixed: bool = False
    bonus: float = 0.0; penalty_on: bool = False; penalty: float = 0.0
    rate: float = 250.0; note: str = ''
    approved_at: str = ''

    @property
    def work_min(self): return max(0, span_minutes(self.start, self.end) - (max(0, int(self.lunch_min or 0)) if self.lunch_on else 0))
    @property
    def extra_min(self): return span_minutes(self.extra_start, self.extra_end) if self.extra_on else 0
    @property
    def total_min(self): return self.work_min + self.extra_min
    @property
    def day_pay(self): return self.work_min / 60.0 * float(self.rate or 0)
    @property
    def extra_pay(self):
        if not self.extra_on: return 0.0
        return float(self.extra_fixed or 0) if self.extra_use_fixed else self.extra_min / 60.0 * float(self.extra_rate or 0)
    @property
    def gross_pay(self): return self.day_pay + self.extra_pay + float(self.bonus or 0)
    @property
    def total_pay(self): return max(0.0, self.gross_pay - (float(self.penalty or 0) if self.penalty_on else 0))
    @property
    def date_obj(self): return dt.date.fromisoformat(self.date)
    @property
    def weekday_name(self): return WEEKDAYS_RU[self.date_obj.weekday()]
    @property
    def is_empty(self): return (self.start is None and self.end is None and not self.works.strip() and not self.extra_on and not float(self.bonus or 0) and not (self.penalty_on and float(self.penalty or 0)))

    def to_dict(self): return asdict(self)
    @staticmethod
    def from_row(row):
        d = dict(row); d.pop('id', None)
        for k in ('lunch_on','extra_on','extra_use_fixed','penalty_on'): d[k] = bool(d.get(k, 0))
        return DayEntry(**d)

def week_start(d): return d - dt.timedelta(days=d.weekday())
def week_range(d):
    s = week_start(d); return s, s + dt.timedelta(days=6)
def week_title(d):
    a,b = week_range(d); return '%02d.%02d – %02d.%02d.%d' % (a.day,a.month,b.day,b.month,b.year)
def month_title(d): return '%s %d' % (MONTHS_RU[d.month-1], d.year)
def month_range(d):
    first = d.replace(day=1)
    nxt = dt.date(first.year + (first.month==12), 1 if first.month==12 else first.month+1, 1)
    return first, nxt - dt.timedelta(days=1)

class Totals:
    def __init__(self, entries):
        self.days = [e for e in entries if not e.is_empty]
        self.work_min = sum(e.work_min for e in self.days); self.extra_min = sum(e.extra_min for e in self.days)
        self.total_min = self.work_min + self.extra_min; self.day_pay = sum(e.day_pay for e in self.days); self.extra_pay = sum(e.extra_pay for e in self.days)
        self.bonus = sum(float(e.bonus or 0) for e in self.days); self.penalty = sum(float(e.penalty or 0) if e.penalty_on else 0 for e in self.days)
        self.total_pay = sum(e.total_pay for e in self.days); self.worked_days = len(self.days)

def default_data_dir():
    return os.environ.get('ANDROID_PRIVATE') or os.environ.get('ANDROID_APP_PATH') or os.path.expanduser('~/.tabel_ucheta_test')

SCHEMA = """
CREATE TABLE IF NOT EXISTS days (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT UNIQUE NOT NULL, start INTEGER, end INTEGER, lunch_on INTEGER DEFAULT 0, lunch_min INTEGER DEFAULT 0, works TEXT DEFAULT '', extra_on INTEGER DEFAULT 0, extra_start INTEGER, extra_end INTEGER, extra_works TEXT DEFAULT '', extra_rate REAL DEFAULT 250, extra_fixed REAL DEFAULT 0, extra_use_fixed INTEGER DEFAULT 0, bonus REAL DEFAULT 0, penalty_on INTEGER DEFAULT 0, penalty REAL DEFAULT 0, rate REAL DEFAULT 250, note TEXT DEFAULT '', approved_at TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_days_date ON days(date);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""
DEFAULT_SETTINGS = {'rate':'250','extra_rate':'250','default_start':'8:00','default_end':'17:00','default_lunch':'60','employee':'','employee_id':'','secret_key':'','organization':'','rounding':'ruble','received_date':'','received':'0'}

class Storage:
    def __init__(self, path=None):
        self.path = path or os.path.join(default_data_dir(), DB_FILENAME); os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.conn = sqlite3.connect(self.path); self.conn.row_factory = sqlite3.Row; self.conn.executescript(SCHEMA)
        self._migrate();
        for k,v in DEFAULT_SETTINGS.items(): self.conn.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
        self.conn.commit()
    def _migrate(self):
        cols = {r['name'] for r in self.conn.execute('PRAGMA table_info(days)')}
        for col,typ in [('penalty_on','INTEGER DEFAULT 0'),('penalty','REAL DEFAULT 0'),('approved_at',"TEXT DEFAULT ''")]:
            if col not in cols: self.conn.execute('ALTER TABLE days ADD COLUMN %s %s' % (col,typ))
    def get(self,key,default=None):
        r=self.conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); return r['value'] if r else (default if default is not None else DEFAULT_SETTINGS.get(key,''))
    def get_float(self,key,default=0.0):
        try:return float(str(self.get(key)).replace(',','.'))
        except (TypeError,ValueError):return default
    def set(self,key,value): self.conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); self.conn.commit()
    def load_day(self,date):
        date=date.isoformat() if isinstance(date,dt.date) else date; r=self.conn.execute('SELECT * FROM days WHERE date=?',(date,)).fetchone()
        return DayEntry.from_row(r) if r else DayEntry(date=date,rate=self.get_float('rate',250),extra_rate=self.get_float('extra_rate',250))
    def save_day(self,e):
        if e.is_empty: self.delete_day(e.date); return
        self.conn.execute('''INSERT INTO days(date,start,end,lunch_on,lunch_min,works,extra_on,extra_start,extra_end,extra_works,extra_rate,extra_fixed,extra_use_fixed,bonus,penalty_on,penalty,rate,note,approved_at) VALUES(:date,:start,:end,:lunch_on,:lunch_min,:works,:extra_on,:extra_start,:extra_end,:extra_works,:extra_rate,:extra_fixed,:extra_use_fixed,:bonus,:penalty_on,:penalty,:rate,:note,:approved_at) ON CONFLICT(date) DO UPDATE SET start=excluded.start,end=excluded.end,lunch_on=excluded.lunch_on,lunch_min=excluded.lunch_min,works=excluded.works,extra_on=excluded.extra_on,extra_start=excluded.extra_start,extra_end=excluded.extra_end,extra_works=excluded.extra_works,extra_rate=excluded.extra_rate,extra_fixed=excluded.extra_fixed,extra_use_fixed=excluded.extra_use_fixed,bonus=excluded.bonus,penalty_on=excluded.penalty_on,penalty=excluded.penalty,rate=excluded.rate,note=excluded.note,approved_at=excluded.approved_at''', {**e.to_dict(),'lunch_on':int(e.lunch_on),'extra_on':int(e.extra_on),'extra_use_fixed':int(e.extra_use_fixed),'penalty_on':int(e.penalty_on)}); self.conn.commit()
    def delete_day(self,date):
        date=date.isoformat() if isinstance(date,dt.date) else date; self.conn.execute('DELETE FROM days WHERE date=?',(date,)); self.conn.commit()
    def range_days(self,d1,d2):
        rows=self.conn.execute('SELECT * FROM days WHERE date BETWEEN ? AND ? ORDER BY date',(d1.isoformat(),d2.isoformat())).fetchall(); saved={r['date']:DayEntry.from_row(r) for r in rows}; out=[]; cur=d1
        while cur<=d2: out.append(saved.get(cur.isoformat(),DayEntry(date=cur.isoformat(),rate=self.get_float('rate',250),extra_rate=self.get_float('extra_rate',250)))); cur+=dt.timedelta(days=1)
        return out
    def week_days(self,anchor): a,b=week_range(anchor); return self.range_days(a,b)
    def month_days(self,anchor): a,b=month_range(anchor); return self.range_days(a,b)
    def week_complete(self,anchor):
        days=[e for e in self.week_days(anchor) if not e.is_empty]; return bool(days) and all(bool(e.approved_at) for e in days)
    def _week_key(self, anchor): return week_start(anchor).isoformat()
    def week_received(self,anchor): return self.get('received_week_' + self._week_key(anchor), '0') == '1'
    def received_on(self,anchor): return self.get('received_on_' + self._week_key(anchor), '')
    def set_received(self,anchor,date):
        key = self._week_key(anchor); self.set('received_week_' + key, '1'); self.set('received_on_' + key, date)
    def export_json(self,path):
        data = {'format_version': 1,
                'settings': {r['key']: r['value'] for r in self.conn.execute('SELECT key,value FROM settings')},
                'days': [DayEntry.from_row(r).to_dict() for r in self.conn.execute('SELECT * FROM days ORDER BY date')]}
        with open(path, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
        return path
    def close(self): self.conn.close()
