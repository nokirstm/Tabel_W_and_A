import copy
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timecard_core import Storage, DayEntry
from backup_restore import parse_backup, preview, restore


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Storage(os.path.join(self.temp.name, 'target.db'))
        self.data = {'settings': {'employee': 'Тест', 'rate': '321'},
                     'days': [DayEntry(date='2026-09-07', start=480, end=1020,
                                       works='Монтаж\nПроверка 🙂', extra_works='Уборка',
                                       penalty_on=True, penalty=100, rate=321).to_dict()]}

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def test_legacy_roundtrip_and_restart(self):
        source = Storage(os.path.join(self.temp.name, 'source.db'))
        source.save_day(DayEntry(**self.data['days'][0]))
        source.set('employee', 'Тест')
        source.set_received(dt.date(2026, 9, 7), '2026-09-10')
        path = os.path.join(self.temp.name, 'export.json')
        source.export_json(path)
        data = parse_backup(Path(path).read_bytes())
        result = restore(self.db, data)
        self.assertEqual(result['added'], 1)
        self.assertTrue(Path(result['snapshot']).exists())
        self.db.close(); self.db = Storage(self.db.path)
        self.assertEqual(self.db.load_day('2026-09-07').to_dict(), self.data['days'][0])
        self.assertTrue(self.db.week_received(dt.date(2026, 9, 7)))
        source.close()

    def test_existing_records_and_settings_not_overwritten(self):
        self.db.save_day(DayEntry(date='2026-09-07', works='Свежее'))
        self.data['days'].append(DayEntry(date='2026-09-08', works='Новое').to_dict())
        result = restore(self.db, self.data)
        self.assertEqual((result['added'], result['skipped']), (1, 1))
        self.assertEqual(self.db.load_day('2026-09-07').works, 'Свежее')
        self.assertEqual(self.db.get('rate'), '250')

    def test_repeated_import_idempotent(self):
        restore(self.db, self.data)
        result = restore(self.db, self.data)
        self.assertEqual((result['added'], result['skipped']), (0, 1))

    def test_preview_does_not_write(self):
        p = preview(self.db, self.data)
        self.assertEqual(p['total'], 1)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM days').fetchone()[0], 0)
        self.assertEqual(self.db.get('employee'), '')

    def test_invalid_rows_reject_entire_file(self):
        for key, value in [('date', 'bad'), ('works', 1), ('rate', float('inf')),
                           ('lunch_on', 'false'), ('start', 1440), ('bonus', -1),
                           ('unknown', 2), ('lunch_min', True)]:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.data)
                bad['days'].append(dict(bad['days'][0], date='2026-09-08'))
                bad['days'][1][key] = value
                with self.assertRaises((ValueError, TypeError)):
                    restore(self.db, bad)
                self.assertEqual(self.db.conn.execute('SELECT count(*) FROM days').fetchone()[0], 0)

    def test_duplicate_date_and_duplicate_json_key(self):
        self.data['days'] *= 2
        with self.assertRaises(ValueError): restore(self.db, self.data)
        with self.assertRaises(ValueError): parse_backup('{"days":[],"days":[],"settings":{}}')

    def test_other_employee_blocked(self):
        self.db.set('employee', 'Другой')
        with self.assertRaises(ValueError): restore(self.db, self.data)

    def test_closed_week_blocked(self):
        self.db.set_received(dt.date(2026, 9, 7), '2026-09-10')
        p = preview(self.db, self.data)
        self.assertEqual(p['skipped'], 1)

    def test_sql_failure_rolls_back_all_rows(self):
        self.data['days'].append(DayEntry(date='2026-09-08', works='Second').to_dict())
        self.db.conn.execute("CREATE TRIGGER fail_second BEFORE INSERT ON days "
                             "WHEN NEW.date = '2026-09-08' BEGIN SELECT RAISE(ABORT, 'injected'); END")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError): restore(self.db, self.data)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM days').fetchone()[0], 0)
        self.assertEqual(self.db.get('employee'), '')

    def test_invalid_json_and_version(self):
        for text in ['no json', '{}', '[]', '{"days":[], "settings":{}, "format_version":2}']:
            with self.assertRaises(ValueError): parse_backup(text)

    def test_empty_backup(self):
        result = restore(self.db, {'days': [], 'settings': {}})
        self.assertEqual(result['added'], 0)

    def test_settings_failure_rolls_back_days(self):
        self.db.conn.execute("CREATE TRIGGER fail_setting BEFORE UPDATE ON settings "
                             "WHEN NEW.key = 'employee' BEGIN SELECT RAISE(ABORT, 'injected'); END")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError): restore(self.db, self.data)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM days').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
