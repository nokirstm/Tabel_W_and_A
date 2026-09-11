"""Desktop Kivy integration check. Does NOT execute Android Java/IME/SAF."""
import datetime as dt
import json
import os
import sys
import tempfile
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['KIVY_NO_ARGS'] = '1'
import main as M
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch
from backup_restore import parse_backup

scratch = tempfile.TemporaryDirectory()
class QAApp(M.TabelApp):
    @property
    def user_data_dir(self):
        return scratch.name
    def load_kv(self, filename=None):
        # Mirror TabelApp's actual automatic loading, not QAApp's inferred filename.
        return super().load_kv(str(Path(M.HERE) / 'tabel.kv'))

app = QAApp()
app._run_prepare()
def frames(n=8):
    for _ in range(n): EventLoop.idle()
frames()
d = app.s_day
assert Path(M.Storage.__module__ and sys.modules['timecard_core'].__file__).parent == Path(M.HERE)
print('PASS Android model selected')

class FakeNativeEditor:
    def __init__(self): self.calls = []
    def open(self, title, text, callback):
        self.calls.append((title, text)); self.callback = callback; return True
    def close(self): pass
sys.modules['native_editor'] = types.SimpleNamespace(NativeEditor=FakeNativeEditor)
os.environ['ANDROID_ARGUMENT'] = 'test-only'

d.load(dt.date(2026, 9, 7)); frames()
# Direct widget event checks connect both entry points to the same editor.
for widget in (d.lbl_works, d.btn_works):
    widget.dispatch('on_release')
    assert d._editor_busy
    d._native_editor.callback('cancel', '')
    assert not d._editor_busy
print('PASS preview and button handlers, cancel, reopen')

# Touch dispatch through actual ScrollView layout, not just event invocation.
for fraction in (.1, .5, .9):
    before = len(d._native_editor.calls)
    x, y = d.lbl_works.to_window(d.lbl_works.x + d.lbl_works.width * fraction, d.lbl_works.center_y)
    touch = UnitTestTouch(x, y)
    touch.touch_down(); frames(2); touch.touch_up(); frames(25)
    assert len(d._native_editor.calls) == before + 1, (fraction, x, y, d.lbl_works.pos, d.lbl_works.size)
    d._native_editor.callback('cancel', '')
print('PASS touch left/center/right of preview through ScrollView')

d.btn_works.dispatch('on_release')
d._native_editor.callback('ok', 'Монтаж\nПроверка 🙂')
d.f_start.input.text = '8:00'; d.f_end.input.text = '17:00'
d.save(); d.load(dt.date(2026, 9, 8)); d.load(dt.date(2026, 9, 7))
assert d._works_text == 'Монтаж\nПроверка 🙂'
print('PASS text save/load with Unicode and newlines')

# Additional-work description uses the same native editor and remains separate.
d.load(dt.date(2026, 9, 10)); frames()
d.t_extra.set(True); d._toggle_panel('extra', True)
for widget in (d.lbl_xworks, d.btn_xworks):
    widget.dispatch('on_release')
    assert d._editor_busy and d._editor_target == 'extra'
    assert d._native_editor.calls[-1][0] == 'Описание дополнительных работ'
    d._native_editor.callback('cancel', '')
    assert not d._editor_busy
d.btn_xworks.dispatch('on_release')
d._native_editor.callback('ok', 'Установка кабеля\nПроверка')
assert d._extra_works_text == 'Установка кабеля\nПроверка'
assert d._works_text == ''
d.f_start.input.text = '8:00'; d.f_end.input.text = '17:00'
d.f_xstart.input.text = '10:00'; d.f_xend.input.text = '12:00'
d.save(); d.load(dt.date(2026, 9, 11)); d.load(dt.date(2026, 9, 10))
assert d._extra_works_text == 'Установка кабеля\nПроверка'
assert d.collect().extra_works == 'Установка кабеля\nПроверка'
print('PASS additional-work native editor and save/load')


d.btn_works.dispatch('on_release')
d.load(dt.date(2026, 9, 8))
d._native_editor.callback('ok', 'WRONG DATE')
assert d._works_text != 'WRONG DATE'
print('PASS stale date result rejected')

old = M.DayEntry(date='2026-09-09', works='Old', rate=123, note='Keep')
app.db.save_day(old); app.db.set('rate', '777'); d.load(dt.date(2026, 9, 9))
d._set_works_text('Edited'); d.save()
assert app.db.load_day(old.date).rate == 123
assert app.db.load_day(old.date).note == 'Keep'
old.approved_at = '2026-09-10'; app.db.save_day(old); d.load(dt.date(2026, 9, 9))
before = len(d._native_editor.calls)
d._open_works_editor()
assert len(d._native_editor.calls) == before
assert d.lbl_works.disabled and d.btn_works.disabled
print('PASS historical rate/note retained; approved day locked')

app.go('set'); frames()
parent = app.s_set.btn_restore.parent
export_button = next(w for w in parent.children if getattr(w, 'text', '') == 'Создать резервную копию')
assert app.s_set.btn_restore.top <= export_button.y
print('PASS restore button below create backup')

controller = app.restore_controller
incoming = {'days': [M.DayEntry(date='2026-08-03', works='Восстановлено').to_dict()], 'settings': {}}
controller.busy = True; app._restoring = True
controller._preview(incoming); frames()
assert controller.popup is not None
controller._finish()
assert app.db.load_day('2026-08-03').is_empty
controller.busy = True; app._restoring = True
controller._preview(incoming); frames(); controller._apply(); frames()
assert app.db.load_day('2026-08-03').works == 'Восстановлено'
assert not app._restoring
print('PASS restore preview/cancel/apply and refresh')

app.on_stop()
os.environ.pop('ANDROID_ARGUMENT', None)
scratch.cleanup()
print('ALL DESKTOP INTEGRATION CHECKS PASSED; Android native calls NOT tested')
