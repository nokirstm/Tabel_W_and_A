# -*- coding: utf-8 -*-
"""Проверка ядра на реальных цифрах из бумажной ведомости и записей за 17–21.08."""
import sys, os, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from timecard_core import (DayEntry, Storage, Totals, parse_time, parse_duration,
                           fmt_hm_short, fmt_money, week_title)

ok = True
def check(name, got, exp):
    global ok
    good = got == exp
    ok &= good
    print(("  OK  " if good else " FAIL "), name, "->", got, "" if good else ("ожидалось " + str(exp)))

print("== разбор времени ==")
check("8",      parse_time("8"), 480)
check("17.27",  parse_time("17.27"), 1047)
check("17:15",  parse_time("17:15"), 1035)
check("0830",   parse_time("0830"), 510)
check("обед 30", parse_duration("30"), 30)
check("обед 1.00", parse_duration("1.00"), 60)

print("\n== строки из карточки за август (ставка 250) ==")
rows = [("8", "17.27", 0, "9.27", 2362),   # в бумаге записано 9.07 — описка, 8:00→17:27 = 9 ч 27 мин
        ("8", "12.30", 0, "4.30", 1125),
        ("8", "17.20", 0, "9.20", 2333),
        ("8", "12.33", 0, "4.33", 1138),
        ("8", "17",    0, "9.00", 2250)]
for s, e, l, exp_hm, exp_pay in rows:
    d = DayEntry(date="2026-08-03", start=parse_time(s), end=parse_time(e),
                 lunch_on=bool(l), lunch_min=l, rate=250)
    check("с %s по %s" % (s, e), (fmt_hm_short(d.work_min), round(d.day_pay)), (exp_hm, exp_pay))

print("\n== неделя 17–21.08 из твоих записей ==")
db = "/tmp/test_tabel.db"
if os.path.exists(db): os.remove(db)
st = Storage(db)
data = [
    ("2026-08-17", "8", "17.15", 0,  "Доски и тюльки", None, None, "", 0),
    ("2026-08-18", "8", "17.27", 0,  "Косьба травы, забор — натягивание сетки, опоры для кубов",
                                       "10.00", "16.30", "Дополнительные работы", 0),
    ("2026-08-19", "8", "17.15", 0,  "Наведение порядка внутри цеха вместе с Ромой", None, None, "", 0),
    ("2026-08-20", "8", "17.15", 0,  "Поездка за водой, косьба травы, укладка дров", None, None, "", 0),
    ("2026-08-21", "8", "17.15", 0,  "Дрова, порядок на территории, с 13.30 ремонт полива, сбор урожая, забор",
                                       None, None, "", 500),
]
for date, s, e, l, w, xs, xe, xw, bonus in data:
    d = DayEntry(date=date, start=parse_time(s), end=parse_time(e),
                 lunch_on=bool(l), lunch_min=l, works=w,
                 extra_on=xs is not None, extra_start=parse_time(xs) if xs else None,
                 extra_end=parse_time(xe) if xe else None, extra_works=xw,
                 extra_rate=250, bonus=bonus, rate=250)
    st.save_day(d)

days = st.week_days(dt.date(2026, 8, 17))
print(" ", week_title(dt.date(2026, 8, 17)))
for d in days:
    if d.is_empty:
        continue
    print("   %s  %s  осн %s  доп %s  = %s" % (
        d.date, d.weekday_name.ljust(11), fmt_hm_short(d.work_min),
        fmt_hm_short(d.extra_min), fmt_money(d.total_pay)))
t = Totals(days)
print("   ИТОГО: дней %d, осн %s, доп %s, всего %s | оплата %s + доп %s + премия %s = %s" % (
    t.worked_days, fmt_hm_short(t.work_min), fmt_hm_short(t.extra_min),
    fmt_hm_short(t.total_min), fmt_money(t.day_pay), fmt_money(t.extra_pay),
    fmt_money(t.bonus), fmt_money(t.total_pay)))

check("часы основные", fmt_hm_short(t.work_min), "46.27")
check("часы доп",      fmt_hm_short(t.extra_min), "6.30")
check("доп оплата",    round(t.extra_pay), 1625)
check("итог недели",   round(t.total_pay), round(t.day_pay + 1625 + 500))

print("\n== история / повторное чтение ==")
st2 = Storage(db)
d = st2.load_day("2026-08-18")
check("обед выключен", d.lunch_on, False)
check("доп сохранены", (d.extra_start, d.extra_end), (600, 990))
check("месяцы в истории", st2.filled_months(), ["2026-08"])
check("недели в истории", len(st2.filled_weeks()), 1)

print("\nРЕЗУЛЬТАТ:", "ВСЕ ТЕСТЫ ПРОЙДЕНЫ" if ok else "ЕСТЬ ОШИБКИ")
