"""Validated manual restoration of Android JSON backups. No UI or Android imports."""
import datetime as dt
import json
import math
import os
import sqlite3
import uuid
from dataclasses import fields
from timecard_core import DayEntry, DEFAULT_SETTINGS, week_start

MAX_BYTES = 8 * 1024 * 1024
MAX_DAYS = 20000
BOOLS = {'lunch_on', 'extra_on', 'extra_use_fixed', 'penalty_on'}
TIMES = {'start', 'end', 'extra_start', 'extra_end'}
MONEY = {'rate', 'extra_rate', 'extra_fixed', 'bonus', 'penalty'}
STRINGS = {'works', 'extra_works', 'note', 'approved_at'}
COLUMNS = tuple(f.name for f in fields(DayEntry))


def _date(value):
    if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError('Некорректная дата в копии')
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Повторяющиеся ключи JSON')
        result[key] = value
    return result


def parse_backup(text):
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            raise ValueError('Файл превышает 8 МБ')
        text = text.decode('utf-8-sig')
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Файл превышает 8 МБ')
    data = json.loads(text, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Недопустимое число JSON')))
    if not isinstance(data, dict) or not {'settings', 'days'} <= data.keys():
        raise ValueError('Это не резервная копия Табеля: нужны settings и days')
    if data.get('format_version', 1) != 1:
        raise ValueError('Версия формата копии не поддерживается')
    if not isinstance(data['settings'], dict) or not isinstance(data['days'], list):
        raise ValueError('Некорректные settings или days')
    if len(data['days']) > MAX_DAYS:
        raise ValueError('Слишком много записей в копии')
    settings = {}
    for key, value in data['settings'].items():
        if not isinstance(value, str) or len(value) > 10000:
            raise ValueError('Некорректный тип настройки')
        if key.startswith(('received_week_', 'received_on_')):
            prefix = 'received_week_' if key.startswith('received_week_') else 'received_on_'
            day = dt.date.fromisoformat(_date(key[len(prefix):]))
            if day.weekday() != 0:
                raise ValueError('Некорректная неделя в копии')
            if prefix == 'received_week_' and value not in ('0', '1'):
                raise ValueError('Некорректный статус недели')
            if prefix == 'received_on_' and value:
                _date(value)
        elif key not in DEFAULT_SETTINGS:
            raise ValueError('Неизвестная настройка в копии: ' + key)
        if key in ('rate', 'extra_rate'):
            number = float(value.replace(',', '.'))
            if not math.isfinite(number) or not 0 <= number <= 1e12:
                raise ValueError('Некорректная ставка')
        settings[key] = value
    rows, seen = [], set()
    for source in data['days']:
        if not isinstance(source, dict) or 'date' not in source:
            raise ValueError('Некорректная запись дня')
        if source.keys() - set(COLUMNS) - {'id'}:
            raise ValueError('Копия содержит неподдерживаемые поля дня')
        day = _date(source['date'])
        if day in seen:
            raise ValueError('Повторяющаяся дата в копии: ' + day)
        seen.add(day)
        row = DayEntry(date=day).to_dict()
        row.update({k: v for k, v in source.items() if k != 'id'})
        for key in BOOLS:
            if type(row[key]) not in (bool, int) or row[key] not in (0, 1):
                raise ValueError('Некорректный переключатель: ' + key)
            row[key] = bool(row[key])
        for key in TIMES:
            if row[key] is not None and (type(row[key]) is not int or not 0 <= row[key] <= 1439):
                raise ValueError('Некорректное время: ' + key)
        if type(row['lunch_min']) is not int or not 0 <= row['lunch_min'] <= 1440:
            raise ValueError('Некорректная длительность обеда')
        for key in MONEY:
            if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or not 0 <= row[key] <= 1e12:
                raise ValueError('Некорректная сумма: ' + key)
        for key in STRINGS:
            if not isinstance(row[key], str) or len(row[key]) > 100000:
                raise ValueError('Некорректный текст: ' + key)
        rows.append(row)
    return {'settings': settings, 'days': rows}


def preview(db, data):
    # Revalidate even when caller supplies an already parsed object.
    data = parse_backup(json.dumps(data, ensure_ascii=False))
    for key in ('employee_id', 'employee'):
        old, new = db.get(key, '').strip(), data['settings'].get(key, '').strip()
        if old and new and old != new:
            raise ValueError('Копия относится к другому сотруднику. Импорт остановлен.')
    existing = {r[0] for r in db.conn.execute('SELECT date FROM days')}
    skipped, eligible = 0, []
    for row in data['days']:
        if row['date'] in existing or db.week_received(dt.date.fromisoformat(row['date'])):
            skipped += 1
        else:
            eligible.append(row)
    dates = sorted(row['date'] for row in data['days'])
    return {'data': data, 'rows': eligible, 'skipped': skipped,
            'total': len(dates), 'first': dates[0] if dates else '—',
            'last': dates[-1] if dates else '—', 'settings': not existing}


def restore(db, data):
    plan = preview(db, data)
    if db.conn.in_transaction:
        raise ValueError('База занята незавершённой операцией')
    snapshot = os.path.join(os.path.dirname(db.path), 'before_restore_' + uuid.uuid4().hex + '.db')
    destination = sqlite3.connect(snapshot)
    try:
        db.conn.backup(destination)
    finally:
        destination.close()
    sql = 'INSERT INTO days (' + ','.join(COLUMNS) + ') VALUES (' + ','.join('?' for _ in COLUMNS) + ')'
    # No save_day()/set(): those methods commit per row and would break atomicity.
    with db.conn:
        for row in plan['rows']:
            db.conn.execute(sql, tuple(row[k] for k in COLUMNS))
        if plan['settings']:
            db.conn.executemany('INSERT INTO settings(key,value) VALUES(?,?) '
                                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                plan['data']['settings'].items())
        check = db.conn.execute('PRAGMA quick_check').fetchone()[0]
        if check != 'ok':
            raise ValueError('Проверка целостности БД не пройдена')
    return {'added': len(plan['rows']), 'skipped': plan['skipped'], 'snapshot': snapshot}
