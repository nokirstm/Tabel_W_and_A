# -*- coding: utf-8 -*-
"""
Табель 2.0 — учёт рабочего времени и выплат.
Android-версия (Kivy). Собирается в .apk через buildozer.
Использует то же ядро расчётов, что и Windows-версия: core/timecard_core.py

ВЕРСИЯ 2.0.0 - Добавлена синхронизация с сервером
"""
import os
import sys
import datetime as dt
import threading

HERE = os.path.dirname(os.path.abspath(__file__))

# Always use Android's own model, including when testing from the repository root.
if HERE in sys.path:
    sys.path.remove(HERE)
sys.path.insert(0, HERE)

from kivy.config import Config
if not os.environ.get("ANDROID_ARGUMENT"):
    Config.set("graphics", "width", "412")
    Config.set("graphics", "height", "870")

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.popup import Popup
from kivy.graphics import Color, RoundedRectangle, Rectangle, Line
from kivy.clock import Clock
from kivy.utils import get_color_from_hex as hexc

from timecard_core import (THEME as T, DayEntry, Storage, Totals, WEEKDAYS_RU,
                          WEEKDAYS_RU_SHORT, MONTHS_RU, parse_time, parse_duration,
                          fmt_time, fmt_hm, fmt_hm_short, fmt_money,
                          week_range, week_title, month_title, month_range)
import reports

# Android system document picker for backups
try:
    from android import activity as android_activity
except ImportError:
    android_activity = None

# Импорт клиента синхронизации
try:
    from sync_client import SyncClient
    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False
    print("Warning: sync_client.py not found, sync disabled")

C = {k: hexc(v) for k, v in T.items()}

# --- шрифты с кириллицей ---
for name, fn in (("Regular", "DejaVuSans.ttf"), ("Bold", "DejaVuSans-Bold.ttf")):
    for base in (os.path.join(HERE, "assets"), HERE,
                 "/usr/share/fonts/truetype/dejavu"):
        f = os.path.join(base, fn)
        if os.path.exists(f):
            LabelBase.register(name=name, fn_regular=f)
            break
    else:
        LabelBase.register(name=name, fn_regular=LabelBase.default_fontPaths[0]
                          if hasattr(LabelBase, "default_fontPaths") else "Roboto")

FONT = "Regular"
FONTB = "Bold"

# ---------------------------------------------------------------- базовые виджеты
class Card(BoxLayout):
    def __init__(self, title=None, bg=None, radius=14, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("padding", [dp(14), dp(12), dp(14), dp(12)])
        kw.setdefault("spacing", dp(8))
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self._collapsed = False
        self._bg = bg or C["surface"]
        with self.canvas.before:
            self._c = Color(*self._bg)
            self._r = RoundedRectangle(radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync)
        if title:
            self.add_widget(TLabel(title, font=FONTB, size=17, color=C["accent_dark"],
                                   height=dp(26)))
        self._auto_h = self.setter("height")
        self.bind(minimum_height=self._auto_h)
    
    def collapse(self, show):
        """Свернуть/развернуть панель (для полей под галочкой)."""
        self._collapsed = not show
        if show:
            self.opacity = 1
            self.disabled = False
            self.bind(minimum_height=self._auto_h)
            self.height = self.minimum_height
        else:
            self.unbind(minimum_height=self._auto_h)
            self.opacity = 0
            self.disabled = True
            self.height = 0
    
    def on_touch_down(self, touch):
        if self._collapsed:
            return False
        return super().on_touch_down(touch)
    
    def on_touch_move(self, touch):
        if self._collapsed:
            return False
        return super().on_touch_move(touch)
    
    def on_touch_up(self, touch):
        if self._collapsed:
            return False
        return super().on_touch_up(touch)
    
    def _sync(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size

class TLabel(Label):
    def __init__(self, text="", size=15, color=None, font=FONT, halign="left",
                 height=None, bold=False, **kw):
        super().__init__(text=text, font_size=sp(size), font_name=font,
                        color=color or C["text"], halign=halign, valign="middle",
                        size_hint_y=None, **kw)
        self._fixed = height
        self.bind(width=lambda *_: setattr(self, "text_size", (self.width, None)))
        self.bind(texture_size=self._resize)
        if height:
            self.height = height
    
    def _resize(self, *_):
        if not self._fixed:
            self.height = self.texture_size[1] + dp(2)

class TInput(TextInput):
    def __init__(self, hint="", numeric=False, height=48, multiline=False, **kw):
        super().__init__(
            hint_text=hint, multiline=multiline,
            background_normal="", background_active="", background_color=C["white"],
            foreground_color=C["text"], cursor_color=C["accent"],
            hint_text_color=C["text_muted"], font_name=FONT, font_size=sp(17),
            padding=[dp(10), dp(12)], size_hint_y=None, height=dp(height),
            input_type="number" if numeric else "text",
            write_tab=False, **kw)
        with self.canvas.after:
            self._c = Color(*C["border"])
            self._l = Line(width=1.2)
        self.bind(pos=self._sync, size=self._sync, focus=self._focus)
    
    def _sync(self, *_):
        self._l.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(8))
    
    def _focus(self, _w, val):
        self._c.rgba = C["accent"] if val else C["border"]

class FlatButton(Button):
    def __init__(self, text, bg=None, fg=None, height=50, size=16, font=FONTB,
                 radius=10, **kw):
        super().__init__(text=text, background_normal="", background_down="",
                        background_color=(0, 0, 0, 0), color=fg or C["white"],
                        font_name=font, font_size=sp(size),
                        size_hint_y=None, height=dp(height), **kw)
        self._bg = bg or C["accent"]
        with self.canvas.before:
            self._c = Color(*self._bg)
            self._r = RoundedRectangle(radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync, state=self._st)
    
    def _sync(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
    
    def _st(self, _w, st):
        r, g, b, a = self._bg
        k = 0.86 if st == "down" else 1.0
        self._c.rgba = (r*k, g*k, b*k, a)

class Toggle(BoxLayout):
    """Галочка: квадрат + подпись, вся строка кликабельна."""
    def __init__(self, text, on_toggle=None, bg=None, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                        height=dp(46), spacing=dp(10), **kw)
        self.active = False
        self.on_toggle = on_toggle
        self.box = Label(text="", size_hint=(None, None), size=(dp(26), dp(26)),
                        pos_hint={"center_y": 0.5}, font_name=FONTB,
                        font_size=sp(16), color=C["white"])
        with self.box.canvas.before:
            self._bc = Color(*C["white"])
            self._br = RoundedRectangle(radius=[dp(6)])
            self._lc = Color(*C["border"])
            self._ln = Line(width=1.4)
        self.box.bind(pos=self._sync, size=self._sync)
        self.mark = TLabel("", size=17, font=FONTB, color=C["white"],
                          halign="center", height=dp(26))
        self.mark.size_hint_x = None
        self.mark.width = dp(0)
        self.lbl = TLabel(text, size=15, font=FONTB)
        self.add_widget(self.box)
        self.add_widget(self.lbl)
        self.bind(on_touch_down=self._touch)
    
    def _sync(self, *_):
        self._br.pos, self._br.size = self.box.pos, self.box.size
        self._ln.rounded_rectangle = (self.box.x, self.box.y, self.box.width,
                                      self.box.height, dp(6))
    
    def set(self, active):
        self.active = active
        if active:
            self._bc.rgba = C["accent"]
            self.mark.text = "✓"
            self.mark.width = dp(26)
        else:
            self._bc.rgba = C["white"]
            self.mark.text = ""
            self.mark.width = dp(0)
    
    def _touch(self, _w, touch):
        if not self.collide_point(*touch.pos):
            return False
        self.set(not self.active)
        if self.on_toggle:
            self.on_toggle(self.active)
        return True

def field(label, hint, numeric=False):
    """Готовый блок: подпись + поле ввода."""
    box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
    box.add_widget(TLabel(label, size=13, color=C["text_muted"], height=dp(20)))
    inp = TInput(hint=hint, numeric=numeric, height=44)
    box.add_widget(inp)
    box.height = dp(68)
    box.input = inp
    return box

def Row(label, value, bold=False, size=15, color=None):
    """Строка итогов: подпись слева, значение справа."""
    row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
    row.add_widget(TLabel(label, size=size, font=FONTB if bold else FONT,
                         color=C["text"], height=dp(24)))
    row.add_widget(TLabel(value, size=size, font=FONTB if bold else FONT,
                         color=color or C["text"], halign="right", height=dp(24)))
    return row

def toast(text, kind="ok"):
    """Простое всплывающее уведомление."""
    color = C["ok"] if kind == "ok" else C["warn"]
    p = Popup(title="", content=TLabel(text, size=14, color=color, halign="center"),
             size_hint=(0.85, 0.18), auto_dismiss=True)
    p.open()
    Clock.schedule_once(lambda *_: p.dismiss(), 2.5)

# ---------------------------------------------------------------- экран ДЕНЬ
class DayScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="day", **kw)
        self.app = app
        self._loading = False
        self._loaded_entry = None
        
        root = BoxLayout(orientation="vertical")
        self.add_widget(root)
        
        # шапка дня
        head = BoxLayout(size_hint_y=None, height=dp(60), padding=[dp(10), dp(6)],
                        spacing=dp(6))
        with head.canvas.before:
            Color(*C["surface"])
            hr = Rectangle()
        head.bind(pos=lambda *a: setattr(hr, "pos", head.pos),
                 size=lambda *a: setattr(hr, "size", head.size))
        
        head.add_widget(FlatButton("<", bg=C["accent_dark"], height=48, size=20,
                                   size_hint_x=None, width=dp(50),
                                   on_release=lambda _: self.shift(-1)))
        
        date_box = BoxLayout(orientation="vertical", spacing=dp(2))
        self.l_wd = TLabel("", size=16, font=FONTB, color=C["accent_dark"],
                          halign="center", height=dp(24))
        self.l_dt = TLabel("", size=12, color=C["text_muted"], halign="center",
                          height=dp(18))
        date_box.add_widget(self.l_wd)
        date_box.add_widget(self.l_dt)
        head.add_widget(date_box)
        
        head.add_widget(FlatButton(">", bg=C["accent_dark"], height=48, size=20,
                                   size_hint_x=None, width=dp(50),
                                   on_release=lambda _: self.shift(1)))
        root.add_widget(head)
        
        # прокрутка с полями
        sc = ScrollView(do_scroll_x=False)
        body = BoxLayout(orientation="vertical", size_hint_y=None,
                        padding=[dp(10), dp(10)], spacing=dp(10))
        body.bind(minimum_height=body.setter("height"))
        sc.add_widget(body)
        root.add_widget(sc)
        
        # --- основные поля ---
        time_card = Card("Рабочее время")
        
        time_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(70), spacing=dp(8))
        self.f_start = field("Начало", "8:00")
        self.f_end = field("Конец", "17:00")
        time_row.add_widget(self.f_start)
        time_row.add_widget(self.f_end)
        time_card.add_widget(time_row)
        
        self.t_lunch = Toggle("Был обед", self._toggle_lunch)
        time_card.add_widget(self.t_lunch)
        
        self.lunch_box = Card(bg=C["surface_alt"], radius=10)
        lunch_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                             height=dp(60), spacing=dp(6))
        self.f_lunch = field("Обед, минут", "60", True)
        lunch_row.add_widget(self.f_lunch)
        self.lunch_box.add_widget(lunch_row)
        
        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                        height=dp(36), spacing=dp(6))
        for mins in (30, 45, 60):
            b = FlatButton(str(mins), bg=C["accent_light"], fg=C["accent_dark"],
                          height=36, size=13, font=FONT,
                          on_release=lambda _b, m=mins: self._set_lunch(m))
            btns.add_widget(b)
        self.lunch_box.add_widget(btns)
        time_card.add_widget(self.lunch_box)
        self.lunch_box.collapse(False)
        
        # Поле "что делал"
        works_card = Card("Объём и качество работ")
        self.lbl_works = TLabel("что делал на работе…", size=13,
                               color=C["text_muted"], height=dp(20))
        works_card.add_widget(self.lbl_works)
        self.txt_works = TInput(hint="", multiline=True, height=80)
        self.txt_works.bind(text=self._works_changed)
        works_card.add_widget(self.txt_works)
        self.btn_works = FlatButton("Редактировать", bg=C["surface_alt"],
                                   fg=C["accent_dark"], height=38, size=13,
                                   font=FONT, on_release=lambda _: self._edit_works())
        works_card.add_widget(self.btn_works)
        
        # Доп работы
        extra_card = Card("Дополнительные работы")
        self.t_extra = Toggle("Были доп. работы", self._toggle_extra)
        extra_card.add_widget(self.t_extra)
        
        self.extra_box = Card(bg=C["surface_alt"], radius=10)
        xtime_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                               height=dp(70), spacing=dp(8))
        self.f_xstart = field("Начало доп.", "")
        self.f_xend = field("Конец доп.", "")
        xtime_row.add_widget(self.f_xstart)
        xtime_row.add_widget(self.f_xend)
        self.extra_box.add_widget(xtime_row)
        
        rate_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(70), spacing=dp(8))
        self.f_xrate = field("Ставка ₽/час", "250", True)
        self.f_xfixed = field("Фикс. сумма ₽", "", True)
        rate_row.add_widget(self.f_xrate)
        rate_row.add_widget(self.f_xfixed)
        self.extra_box.add_widget(rate_row)
        
        self.t_xfixed = Toggle("Оплата фиксированной суммой", self._toggle_xfixed)
        self.extra_box.add_widget(self.t_xfixed)
        
        self.lbl_xworks = TLabel("что делал дополнительно…", size=13,
                                color=C["text_muted"], height=dp(20))
        self.extra_box.add_widget(self.lbl_xworks)
        self.txt_xworks = TInput(hint="", multiline=True, height=80)
        self.txt_xworks.bind(text=self._xworks_changed)
        self.extra_box.add_widget(self.txt_xworks)
        self.btn_xworks = FlatButton("Редактировать", bg=C["accent_light"],
                                    fg=C["accent_dark"], height=38, size=13,
                                    font=FONT, on_release=lambda _: self._edit_xworks())
        self.extra_box.add_widget(self.btn_xworks)
        self.extra_box.collapse(False)
        
        # Премия
        bonus_card = Card("Премия и штрафы")
        self.f_bonus = field("Премия ₽", "", True)
        bonus_card.add_widget(self.f_bonus)
        
        # Кнопки
        btns_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(50), spacing=dp(8))
        btns_row.add_widget(FlatButton("СОХРАНИТЬ", height=50,
                                      on_release=lambda _: self.save()))
        btns_row.add_widget(FlatButton("Очистить", bg=C["danger"], height=50,
                                      on_release=lambda _: self.clear()))
        
        # Итоги дня
        self.totals_card = Card("ИТОГО ЗА ДЕНЬ", bg=hexc("#C9DFF2"))
        self.t_hours = Row("Часов основных", "")
        self.t_xhours = Row("Часов дополнительных", "")
        self.t_day = Row("Оплата за день", "")
        self.t_extra_pay = Row("Доп. работы", "")
        self.t_bonus = Row("Премия", "")
        self.t_total = Row("ВСЕГО", "", bold=True, size=18, color=C["ok"])
        self.t_total.height = dp(32)
        self.totals_card.add_widget(self.t_hours)
        self.totals_card.add_widget(self.t_xhours)
        self.totals_card.add_widget(self.t_day)
        self.totals_card.add_widget(self.t_extra_pay)
        self.totals_card.add_widget(self.t_bonus)
        self.totals_card.add_widget(self.t_total)
        
        body.add_widget(time_card)
        body.add_widget(works_card)
        body.add_widget(extra_card)
        body.add_widget(bonus_card)
        body.add_widget(btns_row)
        body.add_widget(self.totals_card)
        
        # Привязка изменений к пересчёту
        for inp in (self.f_start.input, self.f_end.input, self.f_lunch.input,
                   self.f_xstart.input, self.f_xend.input, self.f_xrate.input,
                   self.f_xfixed.input, self.f_bonus.input):
            inp.bind(text=lambda *_: self.recalc())
    
    def _toggle_panel(self, name, show):
        if name == "lunch":
            self.lunch_box.collapse(show)
        elif name == "extra":
            self.extra_box.collapse(show)
    
    def _toggle_lunch(self, active):
        self._toggle_panel("lunch", active)
        self.recalc()
    
    def _toggle_extra(self, active):
        self._toggle_panel("extra", active)
        self.recalc()
    
    def _toggle_xfixed(self, active):
        self.f_xrate.input.disabled = active
        self.f_xfixed.input.disabled = not active
        self.recalc()
    
    def _set_lunch(self, mins):
        self.f_lunch.input.text = str(mins)
    
    def _works_changed(self, _w, text):
        self._works_text = text
        if text:
            self.lbl_works.text = text
            self.lbl_works.color = C["text"]
        else:
            self.lbl_works.text = "что делал на работе…"
            self.lbl_works.color = C["text_muted"]
    
    def _xworks_changed(self, _w, text):
        self._xworks_text = text
        if text:
            self.lbl_xworks.text = text
            self.lbl_xworks.color = C["text"]
        else:
            self.lbl_xworks.text = "что делал дополнительно…"
            self.lbl_xworks.color = C["text_muted"]
    
    def _set_extra_works_text(self, text):
        self._xworks_text = text or ""
        self.txt_xworks.text = self._xworks_text
        self._xworks_changed(None, self._xworks_text)
    
    def _edit_works(self):
        self.txt_works.focus = True
    
    def _edit_xworks(self):
        self.txt_xworks.focus = True
    
    def collect(self):
        """Собирает данные с экрана в DayEntry."""
        e = DayEntry(date=self.app.current.isoformat(),
                    start=parse_time(self.f_start.input.text),
                    end=parse_time(self.f_end.input.text),
                    lunch_on=self.t_lunch.active,
                    lunch_min=parse_duration(self.f_lunch.input.text),
                    works=self._works_text or "",
                    extra_on=self.t_extra.active,
                    extra_start=parse_time(self.f_xstart.input.text),
                    extra_end=parse_time(self.f_xend.input.text),
                    extra_works=self._xworks_text or "",
                    extra_rate=_f(self.f_xrate.input.text, 250),
                    extra_fixed=_f(self.f_xfixed.input.text, 0),
                    extra_use_fixed=self.t_xfixed.active,
                    bonus=_f(self.f_bonus.input.text, 0),
                    rate=self.app.db.get_float("rate", 250))
        
        # Сохраняем состояние синхронизации если есть
        if self._loaded_entry:
            e.approved_at = self._loaded_entry.approved_at
            e.version = self._loaded_entry.version
            e.sync_status = self._loaded_entry.sync_status
        
        return e
    
    def recalc(self):
        if self._loading:
            return
        e = self.collect()
        self.t_hours.r = Row("Часов основных", fmt_hm(e.work_min))
        self.t_xhours.r = Row("Часов дополнительных", fmt_hm(e.extra_min))
        self.t_day.r = Row("Оплата за день", fmt_money(e.day_pay))
        self.t_extra_pay.r = Row("Доп. работы", fmt_money(e.extra_pay))
        self.t_bonus.r = Row("Премия", fmt_money(e.bonus))
        self.t_total.r = Row("ВСЕГО", fmt_money(e.total_pay), bold=True, size=18, color=C["ok"])
    
    def load(self, d):
        self._loading = True
        self.app.current = d
        e = self.app.db.load_day(d)
        self._loaded_entry = e
        
        self.l_wd.text = WEEKDAYS_RU[d.weekday()]
        self.l_dt.text = "%02d.%02d.%d • %s" % (d.day, d.month, d.year,
                                                  week_title(d))
        
        self.f_start.input.text = fmt_time(e.start) if e.start is not None else ""
        self.f_end.input.text = fmt_time(e.end) if e.end is not None else ""
        
        self.t_lunch.set(e.lunch_on)
        self._toggle_panel("lunch", e.lunch_on)
        self.f_lunch.input.text = str(e.lunch_min or "")
        
        self._works_text = e.works or ""
        self.lbl_works.text = e.works if e.works else "что делал на работе…"
        self.lbl_works.color = C["text"] if e.works else C["text_muted"]
        
        self.t_extra.set(e.extra_on)
        self._toggle_panel("extra", e.extra_on)
        self.f_xstart.input.text = fmt_time(e.extra_start) if e.extra_start is not None else ""
        self.f_xend.input.text = fmt_time(e.extra_end) if e.extra_end is not None else ""
        self.f_xrate.input.text = _num(e.extra_rate)
        self.t_xfixed.set(e.extra_use_fixed)
        self.f_xfixed.input.text = _num(e.extra_fixed) if e.extra_fixed else ""
        self._set_extra_works_text(e.extra_works)
        
        self.f_bonus.input.text = _num(e.bonus) if e.bonus else ""
        
        self._loading = False
        self._set_locked(bool(e.approved_at) or self.app.db.week_received(d))
        self.recalc()
    
    def _set_locked(self, locked):
        """Блокировка редактирования для одобренных записей."""
        controls = (self.f_start.input, self.f_end.input, self.f_lunch.input,
                   self.f_xstart.input, self.f_xend.input,
                   self.f_xrate.input, self.f_xfixed.input,
                   self.f_bonus.input)
        
        self.lbl_works.disabled = locked
        self.btn_works.disabled = locked
        self.lbl_xworks.disabled = locked
        self.btn_xworks.disabled = locked
        
        for w in controls:
            w.disabled = locked
        for w in (self.t_lunch, self.t_extra, self.t_xfixed):
            w.disabled = locked
    
    def shift(self, n):
        self.load(self.app.current + dt.timedelta(days=n))
    
    def defaults(self):
        self.f_start.input.text = self.app.db.get("default_start", "8:00")
        self.f_end.input.text = self.app.db.get("default_end", "17:00")
        self.recalc()
    
    def save(self):
        e = self.collect()
        if e.start is not None and e.end is None:
            toast("Укажите время окончания работы", "warn")
            return
        
        saved = self.app.db.load_day(self.app.current)
        if saved.approved_at or self.app.db.week_received(self.app.current):
            toast("Эта запись уже закрыта", "warn")
            return
        
        # Инкрементируем версию перед сохранением
        new_version = self.app.db.increment_day_version(self.app.current)
        e.version = new_version
        e.sync_status = "local"
        
        self.app.db.save_day(e)
        toast("Сохранено: %s" % fmt_money(e.total_pay))
        
        # Отправляем обновление на сервер
        if self.app.sync_client and SYNC_AVAILABLE:
            employee_id = self.app.db.get("employee_id")
            employee_token = self.app.db.get("employee_token")
            if employee_id and employee_token:
                self.app.sync_client.send_async(
                    'day_updated',
                    employee_id, employee_token,
                    e.date, e.to_dict(), e.version
                )
    
    def clear(self):
        saved = self.app.db.load_day(self.app.current)
        if saved.approved_at or self.app.db.week_received(self.app.current):
            toast("Эта запись уже закрыта", "warn")
            return
        
        self.app.db.delete_day(self.app.current)
        self.load(self.app.current)
        toast("Запись удалена", "warn")

# ---------------------------------------------------------------- экран НЕДЕЛЯ
class WeekScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="week", **kw)
        self.app = app
        root = BoxLayout(orientation="vertical")
        self.add_widget(root)
        
        nav = BoxLayout(size_hint_y=None, height=dp(54), padding=[dp(8), dp(5)],
                       spacing=dp(6))
        with nav.canvas.before:
            Color(*C["surface"])
            nr = Rectangle()
        nav.bind(pos=lambda *a: setattr(nr, "pos", nav.pos),
                size=lambda *a: setattr(nr, "size", nav.size))
        
        nav.add_widget(FlatButton("<", bg=C["accent_dark"], height=44, size=18,
                                  size_hint_x=None, width=dp(50),
                                  on_release=lambda _: self.shift(-1)))
        self.l_title = TLabel("", size=15, font=FONTB, color=C["accent_dark"],
                             halign="center", height=dp(44))
        nav.add_widget(self.l_title)
        nav.add_widget(FlatButton(">", bg=C["accent_dark"], height=44, size=18,
                                  size_hint_x=None, width=dp(50),
                                  on_release=lambda _: self.shift(1)))
        root.add_widget(nav)
        
        sc = ScrollView(do_scroll_x=False)
        self.body = BoxLayout(orientation="vertical", size_hint_y=None,
                             padding=[dp(10), dp(10)], spacing=dp(8))
        self.body.bind(minimum_height=self.body.setter("height"))
        sc.add_widget(self.body)
        root.add_widget(sc)
    
    def shift(self, n):
        self.app.current += dt.timedelta(weeks=n)
        self.refresh()
    
    def refresh(self):
        self.body.clear_widgets()
        d = self.app.current
        self.l_title.text = week_title(d)
        days = self.app.db.week_days(d)
        today = dt.date.today()
        
        for e in days:
            dd = e.date_obj
            bg = C["accent_light"] if dd == today else (
                C["surface_alt"] if dd.weekday() >= 5 else C["surface"])
            
            card = Card(bg=bg, radius=12, padding=[dp(12), dp(10)], spacing=dp(3))
            head = BoxLayout(size_hint_y=None, height=dp(24))
            head.add_widget(TLabel("%s, %02d.%02d" % (WEEKDAYS_RU[dd.weekday()],
                                                       dd.day, dd.month),
                                   size=15, font=FONTB, height=dp(24)))
            head.add_widget(TLabel(fmt_money(e.total_pay) if not e.is_empty else "—",
                                   size=15, font=FONTB, halign="right",
                                   color=C["ok"] if not e.is_empty else C["text_muted"],
                                   height=dp(24)))
            card.add_widget(head)
            
            if not e.is_empty:
                status = "✓ Одобрено" if e.approved_at else "Ожидает одобрения"
                status_color = C["ok"] if e.approved_at else C["warn"]
                card.add_widget(TLabel(status, size=13, font=FONTB,
                                      color=status_color, height=dp(22)))
                
                s = "%s — %s" % (fmt_time(e.start), fmt_time(e.end)) \
                    if e.start is not None and e.end is not None else ""
                if e.lunch_on and e.lunch_min:
                    s += " (обед %d мин)" % e.lunch_min
                s += " ⟶ %s" % fmt_hm_short(e.work_min)
                card.add_widget(TLabel(s, size=13, color=C["text_muted"]))
                
                if e.extra_min or e.extra_pay:
                    card.add_widget(TLabel(
                        "доп.: %s • %s" % (fmt_hm_short(e.extra_min),
                                           fmt_money(e.extra_pay)),
                        size=13, color=C["warn"]))
                
                if e.bonus:
                    card.add_widget(TLabel("премия: %s" % fmt_money(e.bonus),
                                          size=13, color=C["accent_dark"]))
                
                if e.works:
                    card.add_widget(TLabel(e.works, size=13))
            
            btn = FlatButton("просмотр" if e.approved_at else "открыть",
                           bg=C["surface_alt"], fg=C["accent_dark"],
                           height=34, size=12, font=FONT,
                           on_release=lambda _b, x=dd: self.app.open_day(x))
            card.add_widget(btn)
            self.body.add_widget(card)
        
        t = Totals(days)
        tot = Card("Итого за неделю", bg=hexc("#C9DFF2"))
        tot.add_widget(Row("Отработано дней", str(t.worked_days)))
        tot.add_widget(Row("Основных часов", fmt_hm(t.work_min)))
        tot.add_widget(Row("Дополнительных", fmt_hm(t.extra_min)))
        tot.add_widget(Row("Оплата за дни", fmt_money(t.day_pay)))
        tot.add_widget(Row("Доп. работы", fmt_money(t.extra_pay)))
        tot.add_widget(Row("Премия", fmt_money(t.bonus)))
        
        r = Row("К ВЫПЛАТЕ", fmt_money(t.total_pay), bold=True, size=20, color=C["ok"])
        r.height = dp(36)
        tot.add_widget(r)
        self.body.add_widget(tot)
        
        self.body.add_widget(FlatButton("Поделиться отчётом за неделю",
                                       on_release=lambda _: self.app.share_week()))
        
        # Блок выплат
        self.payment_box = Card("Сумма получена", bg=C["surface_alt"], radius=10)
        self.payment_status = TLabel("", size=13, color=C["text_muted"])
        self.payment_box.add_widget(self.payment_status)
        
        self.f_received = field("Дата получения", "дд.мм.гггг")
        self.f_received.input.bind(text=lambda *_: self._received_date_changed())
        self.payment_box.add_widget(self.f_received)
        
        self.received_toggle = Toggle("Получил", self._received_toggle)
        self.payment_box.add_widget(self.received_toggle)
        
        complete = self.app.db.week_complete(d)
        closed = self.app.db.week_received(d)
        
        self.payment_status.text = ("✓ Неделя закрыта окончательно" if closed else
                                   "Все заполненные дни одобрены" if complete else
                                   "Дата станет доступна после одобрения всех заполненных дней")
        
        received_on = self.app.db.received_on(d) if complete else ""
        self.f_received.input.text = received_on
        self.f_received.disabled = not complete or closed
        self.received_toggle.disabled = not complete or closed or not received_on.strip()
        self.received_toggle.set(closed)
        
        self.body.add_widget(self.payment_box)
        self.body.add_widget(TLabel("", height=dp(8)))
    
    def _received_date_changed(self):
        if hasattr(self, "received_toggle"):
            closed = self.app.db.week_received(self.app.current)
            self.received_toggle.disabled = (not self.app.db.week_complete(self.app.current)
                                            or closed
                                            or not self.f_received.input.text.strip())
    
    def _received_toggle(self, active):
        if not active:
            return
        if not self.app.db.week_complete(self.app.current):
            self.received_toggle.set(False)
            toast("Сначала начальник должен одобрить все заполненные дни", "warn")
            return
        
        raw = self.f_received.input.text.strip()
        try:
            got = dt.datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError:
            self.received_toggle.set(False)
            toast("Введите дату в формате ДД.ММ.ГГГГ", "warn")
            return
        
        week_id = self.app.current.isoformat()
        # Получаем текущую версию из payment_state или создаём новую
        state = self.app.db.get_payment_state(week_id)
        version = (state['version'] + 1) if state else 1
        
        self.app.db.set_payment_state(week_id, got.isoformat(), True, version)
        self.refresh()
        toast("Неделя окончательно закрыта", "ok")
        
        # Отправляем подтверждение на сервер
        if self.app.sync_client and SYNC_AVAILABLE:
            employee_id = self.app.db.get("employee_id")
            employee_token = self.app.db.get("employee_token")
            if employee_id and employee_token:
                self.app.sync_client.send_async(
                    'payment_received',
                    employee_id, employee_token,
                    week_id, version
                )

# --------------------------------------------------------------- экран ИСТОРИЯ
class HistoryScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="hist", **kw)
        self.app = app
        self.anchor = dt.date.today().replace(day=1)
        
        root = BoxLayout(orientation="vertical")
        self.add_widget(root)
        
        nav = BoxLayout(size_hint_y=None, height=dp(54), padding=[dp(8), dp(5)],
                       spacing=dp(6))
        with nav.canvas.before:
            Color(*C["surface"])
            nr = Rectangle()
        nav.bind(pos=lambda *a: setattr(nr, "pos", nav.pos),
                size=lambda *a: setattr(nr, "size", nav.size))
        
        nav.add_widget(FlatButton("<", bg=C["accent_dark"], height=44, size=18,
                                  size_hint_x=None, width=dp(50),
                                  on_release=lambda _: self.shift(-1)))
        self.l_title = TLabel("", size=16, font=FONTB, color=C["accent_dark"],
                             halign="center", height=dp(44))
        nav.add_widget(self.l_title)
        nav.add_widget(FlatButton(">", bg=C["accent_dark"], height=44, size=18,
                                  size_hint_x=None, width=dp(50),
                                  on_release=lambda _: self.shift(1)))
        root.add_widget(nav)
        
        sc = ScrollView(do_scroll_x=False)
        self.body = BoxLayout(orientation="vertical", size_hint_y=None,
                             padding=[dp(10), dp(10)], spacing=dp(6))
        self.body.bind(minimum_height=self.body.setter("height"))
        sc.add_widget(self.body)
        root.add_widget(sc)
    
    def shift(self, n):
        m = self.anchor.month - 1 + n
        y = self.anchor.year + m // 12
        self.anchor = dt.date(y, m % 12 + 1, 1)
        self.refresh()
    
    def refresh(self):
        self.body.clear_widgets()
        self.l_title.text = month_title(self.anchor)
        days = self.app.db.month_days(self.anchor)
        wk = []
        
        for e in days:
            dd = e.date_obj
            if not e.is_empty:
                card = Card(radius=10, padding=[dp(12), dp(8)], spacing=dp(2))
                h = BoxLayout(size_hint_y=None, height=dp(22))
                h.add_widget(TLabel("%02d.%02d %s" % (dd.day, dd.month,
                                                       WEEKDAYS_RU_SHORT[dd.weekday()]),
                                   size=14, font=FONTB, height=dp(22)))
                h.add_widget(TLabel("%s • %s" % (fmt_hm_short(e.total_min),
                                                 fmt_money(e.total_pay)),
                                   size=14, font=FONTB, halign="right",
                                   color=C["ok"], height=dp(22)))
                card.add_widget(h)
                
                if e.works:
                    card.add_widget(TLabel(e.works, size=12, color=C["text_muted"]))
                
                card.add_widget(FlatButton("открыть", bg=C["surface_alt"],
                                          fg=C["accent_dark"], height=30, size=11,
                                          font=FONT,
                                          on_release=lambda _b, x=dd: self.app.open_day(x)))
                self.body.add_widget(card)
                wk.append(e)
            
            if dd.weekday() == 6 or dd == days[-1].date_obj:
                t = Totals(wk)
                if t.worked_days:
                    c = Card(bg=hexc("#E3EDF7"), radius=8, padding=[dp(12), dp(6)])
                    c.add_widget(Row("неделя: %d дн., %s" % (t.worked_days,
                                                             fmt_hm_short(t.total_min)),
                                    fmt_money(t.total_pay), bold=True, size=13,
                                    color=C["accent_dark"]))
                    self.body.add_widget(c)
                wk = []
        
        mt = Totals(days)
        tot = Card("Итого за %s" % month_title(self.anchor), bg=hexc("#C9DFF2"))
        tot.add_widget(Row("Отработано дней", str(mt.worked_days)))
        tot.add_widget(Row("Часов основных", fmt_hm(mt.work_min)))
        tot.add_widget(Row("Часов дополнительных", fmt_hm(mt.extra_min)))
        tot.add_widget(Row("Оплата за дни", fmt_money(mt.day_pay)))
        tot.add_widget(Row("Доп. работы", fmt_money(mt.extra_pay)))
        tot.add_widget(Row("Премии", fmt_money(mt.bonus)))
        
        r = Row("ВСЕГО", fmt_money(mt.total_pay), bold=True, size=20, color=C["ok"])
        r.height = dp(36)
        tot.add_widget(r)
        self.body.add_widget(tot)
        
        self.body.add_widget(FlatButton("Поделиться отчётом за месяц",
                                       on_release=lambda _: self.app.share_month(self.anchor)))
        self.body.add_widget(TLabel("", height=dp(8)))

# ------------------------------------------------------------- экран НАСТРОЙКИ
class SettingsScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="set", **kw)
        self.app = app
        
        sc = ScrollView(do_scroll_x=False)
        self.add_widget(sc)
        
        body = BoxLayout(orientation="vertical", size_hint_y=None,
                        padding=[dp(10), dp(12)], spacing=dp(10))
        body.bind(minimum_height=body.setter("height"))
        sc.add_widget(body)
        
        # Оплата
        c1 = Card("Оплата")
        self.f_rate = field("Ставка за час основной работы, ₽", "250", True)
        self.f_xrate = field("Ставка за час доп. работ, ₽", "250", True)
        c1.add_widget(self.f_rate)
        c1.add_widget(self.f_xrate)
        body.add_widget(c1)
        
        # По умолчанию
        c2 = Card("По умолчанию для нового дня")
        self.f_ds = field("Начало работы", "8:00")
        self.f_de = field("Конец работы", "17:00")
        self.f_dl = field("Обед, минут", "60", True)
        for f in (self.f_ds, self.f_de, self.f_dl):
            c2.add_widget(f)
        body.add_widget(c2)
        
        # Данные для отчётов
        c3 = Card("Данные для отчётов")
        self.f_emp = field("Ф. И. О. работника", "")
        self.f_emp_key = field("Секретный ключ сотрудника", "")
        self.f_emp_id = field("employee_id (заполняется синхронизацией)", "")
        self.f_org = field("Организация / участок", "")
        c3.add_widget(self.f_emp)
        c3.add_widget(self.f_emp_key)
        c3.add_widget(self.f_emp_id)
        c3.add_widget(self.f_org)
        body.add_widget(c3)
        
        # Синхронизация
        if SYNC_AVAILABLE:
            c_sync = Card("Синхронизация с сервером", bg=hexc("#E3EDF7"))
            self.f_device_id = field("ID устройства (автоматически)", "")
            self.f_device_id.input.disabled = True
            c_sync.add_widget(self.f_device_id)
            
            self.btn_bind = FlatButton("ПРИВЯЗАТЬ УСТРОЙСТВО", bg=C["accent"],
                                      height=50,
                                      on_release=lambda _: self.bind_device())
            c_sync.add_widget(self.btn_bind)
            
            body.add_widget(c_sync)
        
        body.add_widget(FlatButton("СОХРАНИТЬ НАСТРОЙКИ", height=54,
                                  on_release=lambda _: self.save()))
        
        # Данные
        c4 = Card("Данные")
        c4.add_widget(TLabel("База: " + self.app.db.path, size=11,
                            color=C["text_muted"]))
        c4.add_widget(FlatButton("Создать резервную копию", bg=C["surface_alt"],
                                fg=C["text"], font=FONT, height=46,
                                on_release=lambda _: self.backup()))
        c4.add_widget(FlatButton("Восстановить из резервной копии", bg=C["surface_alt"],
                                fg=C["text"], font=FONT, height=52, size=13,
                                on_release=lambda _: self.app.restore_controller.open()))
        body.add_widget(c4)
        
        body.add_widget(TLabel("Табель 2.0 • учёт рабочего времени и выплат\nверсия 2.0.0",
                               size=12, color=C["text_muted"], halign="center"))
        
        self.load()
    
    def load(self):
        db = self.app.db
        self.f_rate.input.text = db.get("rate", "250")
        self.f_xrate.input.text = db.get("extra_rate", "250")
        self.f_ds.input.text = db.get("default_start", "8:00")
        self.f_de.input.text = db.get("default_end", "17:00")
        self.f_dl.input.text = db.get("default_lunch", "60")
        self.f_emp.input.text = db.get("employee", "")
        self.f_emp_key.input.text = db.get("secret_key", "")
        self.f_emp_id.input.text = db.get("employee_id", "")
        self.f_org.input.text = db.get("organization", "")
        
        if SYNC_AVAILABLE and hasattr(self, 'f_device_id'):
            device_id = self.app.sync_client.device_id if self.app.sync_client else ""
            self.f_device_id.input.text = device_id
    
    def save(self):
        db = self.app.db
        db.set("rate", _f(self.f_rate.input.text, 250))
        db.set("extra_rate", _f(self.f_xrate.input.text, 250))
        db.set("default_start", self.f_ds.input.text or "8:00")
        db.set("default_end", self.f_de.input.text or "17:00")
        db.set("default_lunch", self.f_dl.input.text or "60")
        db.set("employee", self.f_emp.input.text)
        db.set("secret_key", self.f_emp_key.input.text)
        db.set("employee_id", self.f_emp_id.input.text.strip())
        db.set("organization", self.f_org.input.text)
        
        # Сохраняем credentials в sync_client
        if SYNC_AVAILABLE and self.app.sync_client:
            emp_id = self.f_emp_id.input.text.strip()
            emp_token = self.f_emp_key.input.text.strip()
            if emp_id and emp_token:
                self.app.sync_client.set_credentials(emp_id, emp_token)
        
        toast("Настройки сохранены")
    
    def bind_device(self):
        """Привязка устройства к сотруднику через employee_token."""
        if not SYNC_AVAILABLE or not self.app.sync_client:
            toast("Синхронизация недоступна", "warn")
            return
        
        token = self.f_emp_key.input.text.strip()
        if not token:
            toast("Введите секретный ключ сотрудника", "warn")
            return
        
        def callback(result):
            if result.get('ok'):
                status = result.get('status', '')
                if status == 'linked' or status == 'already_linked':
                    emp_id = result.get('employee_id', '')
                    emp_token = result.get('employee_token', '')
                    
                    # Сохраняем в БД
                    self.app.db.set("employee_id", emp_id)
                    self.app.db.set("employee_token", emp_token)
                    
                    # Устанавливаем в клиент
                    self.app.sync_client.set_credentials(emp_id, emp_token)
                    
                    # Обновляем UI
                    Clock.schedule_once(lambda *_: self.load(), 0)
                    toast("✓ Устройство успешно привязано!", "ok")
                else:
                    toast(f"Статус: {status}", "ok")
            else:
                error = result.get('error', 'unknown error')
                toast(f"Ошибка привязки: {error}", "warn")
        
        # Отправляем запрос асинхронно
        self.app.sync_client.send_async('bind_device', token, callback=callback)
    
    def backup(self):
        """Создание резервной копии."""
        p = os.path.join(
            self.app.data_dir,
            "tabel_backup_%s.json" % dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        )
        
        if getattr(self.app, '_restoring', False) or self.app._backup_pending_path:
            return
        
        try:
            self.app.db.export_json(p)
        except Exception as ex:
            self.app._popup('Ошибка резервной копии', str(ex))
            return
        
        if android_activity is None or not os.environ.get("ANDROID_ARGUMENT"):
            toast("Копия создана: " + p, "ok")
            return
        
        try:
            self.app.begin_backup_save(p)
        except Exception as ex:
            toast("Не удалось открыть окно сохранения: %s" % ex, "warn")

# ---------------------------------------------------------------- приложение
class TabelApp(App):
    title = "Табель 2.0"
    
    def build(self):
        self.data_dir = self.user_data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.db = Storage(os.path.join(self.data_dir, "timecard.db"))
        self.current = dt.date.today()
        
        # Переменные для резервного копирования
        self._backup_pending_path = None
        self._backup_result_bound = False
        self._restoring = False
        
        # Инициализация контроллера восстановления
        from restore_ui import RestoreController
        self.restore_controller = RestoreController(self)
        
        # === ИНИЦИАЛИЗАЦИЯ КЛИЕНТА СИНХРОНИЗАЦИИ ===
        self.sync_client = None
        self.sync_event = None
        
        if SYNC_AVAILABLE:
            api_url = "https://script.google.com/macros/s/AKfycbwDWAS8t__5y3WdFudGQa8OMyWxxBYl56tiJY5RHjR1EmBPiyTrlXUpa2CcmI-q3sQBdQ/exec"
            # ВНИМАНИЕ: Здесь должен быть реальный токен! Временно используем заглушку
            # В production нужно получать из настроек или хардкодить
            api_token = self.db.get("api_token", "28096b2395454f05a7ce7a2b0fcfe3b2e58fd9bed8d5465db4560056a662659c")
            device_id_file = os.path.join(self.data_dir, "device_id.txt")
            
            self.sync_client = SyncClient(api_url, api_token, device_id_file)
            
            # Загружаем credentials из БД
            emp_id = self.db.get("employee_id")
            emp_token = self.db.get("employee_token")
            if emp_id and emp_token:
                self.sync_client.set_credentials(emp_id, emp_token)
            
            # Запускаем фоновую синхронизацию каждые 30 секунд
            self.sync_event = Clock.schedule_interval(self._poll_sync, 30)
        
        Window.clearcolor = C["bg"]
        root = BoxLayout(orientation="vertical")
        
        # шапка
        head = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(64),
                        padding=[dp(16), dp(8)])
        with head.canvas.before:
            Color(*C["accent"])
            hr = Rectangle()
        head.bind(pos=lambda *a: setattr(hr, "pos", head.pos),
                 size=lambda *a: setattr(hr, "size", head.size))
        head.add_widget(TLabel("ТАБЕЛЬ 2.0", size=20, font=FONTB, color=C["white"],
                               height=dp(28)))
        today = dt.date.today()
        head.add_widget(TLabel("%s, %d %s %d" % (WEEKDAYS_RU[today.weekday()], today.day,
                                                  MONTHS_RU[today.month-1].lower(),
                                                  today.year),
                               size=12, color=hexc("#DCEBF8"), height=dp(20)))
        root.add_widget(head)
        
        self.sm = ScreenManager(transition=SlideTransition(duration=0.18))
        self.s_day = DayScreen(self)
        self.s_week = WeekScreen(self)
        self.s_hist = HistoryScreen(self)
        self.s_set = SettingsScreen(self)
        for s in (self.s_day, self.s_week, self.s_hist, self.s_set):
            self.sm.add_widget(s)
        root.add_widget(self.sm)
        
        # нижняя навигация
        nav = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(2),
                       padding=[dp(4), dp(4)])
        with nav.canvas.before:
            Color(*C["surface"])
            nr = Rectangle()
        Color(*C["border"])
        nl = Line(width=1)
        nav.bind(pos=lambda *a: (setattr(nr, "pos", nav.pos),
                                 setattr(nl, "points", [nav.x, nav.top,
                                                         nav.right, nav.top])),
                size=lambda *a: (setattr(nr, "size", nav.size),
                                 setattr(nl, "points", [nav.x, nav.top,
                                                         nav.right, nav.top])))
        self.nav_btns = {}
        for key, label in (("day", "День"), ("week", "Неделя"),
                           ("hist", "История"), ("set", "Настройки")):
            b = FlatButton(label, bg=C["surface"], fg=C["text_muted"], height=50,
                          size=13, font=FONT, radius=8,
                          on_release=lambda _b, k=key: self.go(k))
            self.nav_btns[key] = b
            nav.add_widget(b)
        root.add_widget(nav)
        
        self.s_day.load(self.current)
        self.go("day")
        return root
    
    def _poll_sync(self, dt):
        """Фоновая синхронизация - получение команд из очереди."""
        if not self.sync_client or not SYNC_AVAILABLE:
            return
        
        def process_commands(result):
            if not result.get('ok'):
                return
            
            items = result.get('items', [])
            if not items:
                return
            
            for item in items:
                command = item.get('command')
                payload = item.get('payload', {})
                
                if command == 'day_approved':
                    date = payload.get('date')
                    version = payload.get('version')
                    if date:
                        # Проверяем версию перед отметкой
                        current_version = self.db.get_day_version(date)
                        if version and current_version <= version:
                            self.db.mark_approved(date)
                            # Обновляем UI если мы на этом дне
                            if date == self.current.isoformat():
                                Clock.schedule_once(lambda *_: self.s_day.load(self.current), 0)
                
                elif command == 'payment_received':
                    week_id = payload.get('week_id')
                    if week_id:
                        try:
                            week_date = dt.date.fromisoformat(week_id)
                            state = self.db.get_payment_state(week_date)
                            if state:
                                # Обновляем статус выплаты
                                self.db.set_payment_state(week_date, 
                                                         state['payment_date'], 
                                                         True, 
                                                         state['version'])
                            # Обновляем UI если мы на этой неделе
                            if week_date == self.current:
                                Clock.schedule_once(lambda *_: self.s_week.refresh(), 0)
                        except Exception:
                            pass
        
        self.sync_client.send_async('poll_commands', callback=process_commands)
    
    def go(self, key):
        if key == "week":
            self.s_week.refresh()
        elif key == "hist":
            self.s_hist.anchor = self.current.replace(day=1)
            self.s_hist.refresh()
        elif key == "set":
            self.s_set.load()
        self.sm.current = key
        for k, b in self.nav_btns.items():
            act = (k == key)
            b._bg = C["accent_light"] if act else C["surface"]
            b._c.rgba = b._bg
            b.color = C["accent_dark"] if act else C["text_muted"]
            b.font_name = FONTB if act else FONT
    
    def open_day(self, d):
        self.s_day.load(d)
        self.go("day")
    
    # -- «поделиться» текстовым отчётом --
    def _share(self, text):
        try:
            from jnius import autoclass, cast
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            String = autoclass("java.lang.String")
            intent = Intent()
            intent.setAction(Intent.ACTION_SEND)
            intent.setType("text/plain")
            intent.putExtra(Intent.EXTRA_TEXT, cast("java.lang.CharSequence",
                                                     String(text)))
            act = PythonActivity.mActivity
            act.startActivity(Intent.createChooser(intent, cast(
                "java.lang.CharSequence", String("Отправить отчёт"))))
        except Exception:
            p = os.path.join(self.data_dir, "otchet.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            self._popup("Отчёт", text)
    
    def _popup(self, title, text):
        sc = ScrollView()
        lbl = TLabel(text, size=13)
        lbl.font_name = "Regular"
        sc.add_widget(lbl)
        Popup(title=title, content=sc, size_hint=(0.92, 0.8),
             title_font=FONTB).open()
    
    def begin_backup_save(self, path):
        if self._backup_pending_path or self._restoring:
            toast("Операция с копией уже выполняется", "warn")
            return
        
        if android_activity is None:
            return
        
        self._backup_pending_path = path
        try:
            from android.runnable import run_on_ui_thread
            android_activity.bind(on_activity_result=self._on_backup_result)
            self._backup_result_bound = True
            
            @run_on_ui_thread
            def launch():
                try:
                    from jnius import autoclass
                    Intent = autoclass("android.content.Intent")
                    intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
                    intent.addCategory(Intent.CATEGORY_OPENABLE)
                    intent.setType("application/json")
                    intent.putExtra(Intent.EXTRA_TITLE, os.path.basename(path))
                    autoclass("org.kivy.android.PythonActivity").mActivity.startActivityForResult(intent, 4817)
                except Exception as ex:
                    Clock.schedule_once(lambda _dt, msg=str(ex): self._backup_done(msg), 0)
            launch()
        except Exception as ex:
            self._backup_done(str(ex))
    
    def _backup_done(self, error=None, cancelled=False):
        if self._backup_result_bound:
            android_activity.unbind(on_activity_result=self._on_backup_result)
            self._backup_result_bound = False
        
        self._backup_pending_path = None
        
        if getattr(self, '_stopping', False):
            return
        
        if error:
            self._popup("Ошибка сохранения копии", error)
        elif cancelled:
            toast("Сохранение отменено", "warn")
        else:
            toast("Резервная копия сохранена", "ok")
    
    def _on_backup_result(self, request_code, result_code, intent):
        if request_code != 4817:
            return
        try:
            uri = str(intent.getData().toString()) if result_code == -1 and intent is not None and intent.getData() is not None else None
            Clock.schedule_once(lambda _dt: self._write_backup_uri(uri), 0)
        except Exception as ex:
            Clock.schedule_once(lambda _dt, msg=str(ex): self._backup_done(msg), 0)
    
    def _write_backup_uri(self, uri):
        path = self._backup_pending_path
        if getattr(self, '_stopping', False) or not path:
            return
        
        if self._backup_result_bound:
            android_activity.unbind(on_activity_result=self._on_backup_result)
            self._backup_result_bound = False
        
        if uri is None:
            self._backup_done(cancelled=True)
            return
        
        import threading
        
        def copy_file():
            try:
                from jnius import autoclass
                Uri = autoclass("android.net.Uri")
                resolver = autoclass("org.kivy.android.PythonActivity").mActivity.getContentResolver()
                output = resolver.openOutputStream(Uri.parse(uri), "wt")
                if output is None:
                    raise IOError("Не удалось открыть файл")
                try:
                    with open(path, "rb") as source:
                        while True:
                            chunk = source.read(65536)
                            if not chunk:
                                break
                            output.write(bytearray(chunk))
                    output.flush()
                finally:
                    output.close()
                Clock.schedule_once(lambda _dt: self._backup_done(), 0)
            except Exception as ex:
                Clock.schedule_once(lambda _dt, msg=str(ex): self._backup_done(msg), 0)
        
        threading.Thread(target=copy_file, daemon=True).start()
    
    def share_week(self):
        days = self.db.week_days(self.current)
        self._share(reports.export_text(days, "Табель 2.0. Неделя " +
                                        week_title(self.current)))
    
    def share_month(self, anchor):
        days = self.db.month_days(anchor)
        self._share(reports.export_text(days, "Табель 2.0. " + month_title(anchor)))
    
    def on_pause(self):
        if getattr(self, '_restoring', False):
            return True
        try:
            e = self.s_day.collect()
            saved = self.db.load_day(self.current)
            if not e.is_empty and not saved.approved_at and not self.db.week_received(self.current):
                self.db.save_day(e)
        except Exception:
            pass
        return True
    
    def on_stop(self):
        self._stopping = True
        self.on_pause()
        
        # Останавливаем фоновую синхронизацию
        if self.sync_event:
            self.sync_event.cancel()
        
        try:
            self.restore_controller.close()
            if self._backup_result_bound:
                android_activity.unbind(on_activity_result=self._on_backup_result)
                self._backup_result_bound = False
        finally:
            self.db.close()

def _f(text, default=0.0):
    try:
        return float(str(text).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return default

def _num(v):
    v = float(v or 0)
    return str(int(v)) if abs(v - int(v)) < 1e-9 else ("%.2f" % v)

if __name__ == "__main__":
    TabelApp().run()
