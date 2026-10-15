# -- coding: utf-8 --
"""График заработков: диалог на Tkinter Canvas без внешних библиотек.
Составные столбцы (основная работа / доп. / премия), красные блоки штрафов
у верхней линии, легенда и переключатель вида «неделя / месяц / год»."""
import math
import datetime as dt
import tkinter as tk
from tkinter import ttk
from timecard_core import (THEME as T, Totals, WEEKDAYS_RU_SHORT, MONTHS_RU,
                           week_start, week_range, month_range, fmt_money)
import ui_kit as ui
from ui_kit import FONT, F_BODY, F_SMALL

MAIN_COLOR = "#2f81f1"
EXTRA_COLOR = "#d762de"
BONUS_COLOR = "#2f81f1"   # премия — цвет как в таблице недели (скриншот)
PEN_COLOR = "#cd142e"


def _num(v):
    return "{:,}".format(int(round(float(v or 0)))).replace(",", " ")


def _nice_step(x):
    if x <= 0:
        return 1
    p = 10 ** int(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * p >= x:
            return m * p
    return 10 * p


def build_groups(days, mode, anchor):
    """Возвращает список (подпись, Totals) для выбранного вида."""
    mapping = {e.date: e for e in days}
    groups = []
    if mode == "week":
        a, b = week_range(anchor)
        cur = a
        while cur <= b:
            e = mapping.get(cur.isoformat())
            groups.append(("%s %02d.%02d" % (WEEKDAYS_RU_SHORT[cur.weekday()],
                                             cur.day, cur.month),
                           Totals([e] if e else [])))
            cur += dt.timedelta(days=1)
    elif mode == "month":
        a, b = month_range(anchor)
        cur = week_start(a)
        i = 1
        while cur <= b:
            we = cur + dt.timedelta(days=6)
            seg = []
            for k in range(7):
                d = cur + dt.timedelta(days=k)
                if a.isoformat() <= d.isoformat() <= b.isoformat():
                    e = mapping.get(d.isoformat())
                    if e:
                        seg.append(e)
            groups.append(("Нед %d (%02d.%02d–%02d.%02d)"
                           % (i, cur.day, cur.month, we.day, we.month),
                           Totals(seg)))
            cur += dt.timedelta(days=7)
            i += 1
    else:
        for m in range(1, 13):
            seg = [e for e in days
                   if e.date_obj.year == anchor.year and e.date_obj.month == m]
            groups.append((MONTHS_RU[m - 1][:3], Totals(seg)))
    return groups


class ChartDialog(tk.Toplevel):
    """provider(mode) -> (title, anchor_date, days)."""

    MODE_TITLES = {"week": "за неделю", "month": "за месяц", "year": "за год"}

    def __init__(self, master, subject, provider, mode="week"):
        super().__init__(master)
        self.subject = subject
        self.provider = provider
        self.mode = mode
        self.title("График — " + subject)
        self.geometry("980x640")
        self.minsize(720, 480)
        self.configure(bg=T["bg"])
        self.transient(master)

        top = tk.Frame(self, bg=T["bg"])
        top.pack(fill="x", padx=14, pady=(12, 6))
        self.btn_view = ttk.Button(top, text="Вид отображения: " + self.MODE_TITLES[mode],
                                   style="Ghost.TButton", command=self._open_mode_menu)
        self.btn_view.pack(side="left")
        self.lbl_title = tk.Label(top, bg=T["bg"], fg=T["accent_dark"],
                                  font=ui.F_H2, text="")
        self.lbl_title.pack(side="left", padx=14)
        self.lbl_info = tk.Label(top, bg=T["bg"], fg=T["text_muted"], font=F_SMALL,
                                 text="Клик по столбцу — разбивка сумм", anchor="e")
        self.lbl_info.pack(side="right", fill="x", expand=True, padx=6)

        body = tk.Frame(self, bg=T["surface"], highlightbackground=T["border"],
                        highlightthickness=1)
        body.pack(fill="both", expand=True, padx=14, pady=6)
        self.canvas = tk.Canvas(body, bg="#FFFFFF", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self._on_click)

        leg = tk.Frame(self, bg=T["bg"])
        leg.pack(fill="x", padx=14, pady=(4, 12))
        for color, text in ((MAIN_COLOR, "Основные работы"),
                            (EXTRA_COLOR, "Дополнительные работы"),
                            (BONUS_COLOR, "Премия"),
                            (PEN_COLOR, "Штраф")):
            item = tk.Frame(leg, bg=T["bg"])
            item.pack(side="left", padx=(0, 22))
            sq = tk.Canvas(item, width=18, height=18, bg=T["bg"], highlightthickness=0)
            sq.pack(side="left")
            sq.create_rectangle(2, 2, 16, 16, fill=color, outline=color)
            tk.Label(item, text="— " + text, bg=T["bg"], fg=T["text"],
                     font=F_BODY).pack(side="left", padx=(6, 0))
        self._bars = []
        self.redraw()

    def _open_mode_menu(self):
        m = tk.Menu(self, tearoff=0)
        for key in ("week", "month", "year"):
            m.add_command(label=self.MODE_TITLES[key],
                          command=lambda k=key: self._set_mode(k))
        m.tk_popup(self.btn_view.winfo_rootx(),
                   self.btn_view.winfo_rooty() + self.btn_view.winfo_height())

    def _set_mode(self, mode):
        self.mode = mode
        self.btn_view.config(text="Вид отображения: " + self.MODE_TITLES[mode])
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        self._bars = []
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 80 or h < 80:
            return
        title, anchor, days = self.provider(self.mode)
        groups = build_groups(days, self.mode, anchor)
        self.lbl_title.config(text="%s — %s" % (title, self.subject))
        left, right, bottom = 84, 24, 46
        has_pen = any(g.penalty > 0 for _, g in groups)
        pen_zone = 92 if has_pen else 22
        top = 16 + pen_zone
        plot_h = h - top - bottom
        plot_w = w - left - right
        if plot_h <= 20 or plot_w <= 20:
            return
        max_stack = max([g.day_pay + g.extra_pay + g.bonus for _, g in groups] + [0])
        max_pen = max([g.penalty for _, g in groups] + [0])
        if max_stack <= 0 and max_pen <= 0:
            self.canvas.create_text(w / 2, h / 2, text="Нет данных за период",
                                    fill=T["text_muted"], font=ui.F_H2)
            return
        max_stack = max_stack or 1
        # оси
        self.canvas.create_line(left, top - 6, left, h - bottom, fill="#22313F", width=2)
        self.canvas.create_line(left, h - bottom, w - right, h - bottom,
                                fill="#22313F", width=2)
        # линия штрафов сверху
        if max_pen > 0:
            self.canvas.create_line(left, 26, w - right, 26, fill="#000000", width=3)
            self.canvas.create_text(left + 4, 12, text="ШТРАФ", anchor="w",
                                    fill=PEN_COLOR, font=(FONT, 11, "bold"))
        # насечки оси Y
        step = _nice_step(max_stack / 4.0)
        v = 0.0
        while v <= max_stack + 1e-9:
            y = h - bottom - (v / max_stack) * plot_h
            self.canvas.create_line(left - 5, y, left, y, fill="#22313F")
            self.canvas.create_text(left - 9, y, text=_num(v), anchor="e",
                                    fill=T["text_muted"], font=F_SMALL)
            v += step
        n = len(groups)
        slot = plot_w / max(1, n)
        bar_w = min(64, slot * 0.55)
        for i, (label, g) in enumerate(groups):
            cx = left + slot * (i + 0.5)
            y = h - bottom
            for value, color in ((g.day_pay, MAIN_COLOR),
                                 (g.extra_pay, EXTRA_COLOR),
                                 (g.bonus, BONUS_COLOR)):
                if value <= 0:
                    continue
                hh = value / max_stack * plot_h
                # белая обводка разделяет сегменты одинакового цвета
                self.canvas.create_rectangle(cx - bar_w / 2, y - hh, cx + bar_w / 2, y,
                                             fill=color, outline="#FFFFFF", width=1)
                y -= hh
            if g.penalty > 0:
                ph = 10 + (g.penalty / max_pen) * (pen_zone - 46)
                self.canvas.create_rectangle(cx - bar_w / 2, 30, cx + bar_w / 2, 30 + ph,
                                             fill=PEN_COLOR, outline=PEN_COLOR)
                self.canvas.create_text(cx, 30 + ph + 10, text=_num(g.penalty),
                                        fill="#000000", font=(FONT, 10, "bold"))
            if g.total_pay:
                self.canvas.create_text(cx, y - 6, text=_num(g.total_pay), anchor="s",
                                        fill=T["accent_dark"], font=(FONT, 10, "bold"))
            self.canvas.create_text(cx, h - bottom + 8, text=label, anchor="n",
                                    fill=T["text"], font=F_SMALL)
            self._bars.append((cx - slot / 2, cx + slot / 2, label, g))

    def _on_click(self, event):
        for x0, x1, label, g in self._bars:
            if x0 <= event.x <= x1:
                self.lbl_info.config(
                    text="%s: основная %s + доп %s + премия %s − штраф %s = %s"
                         % (label, fmt_money(g.day_pay), fmt_money(g.extra_pay),
                            fmt_money(g.bonus), fmt_money(g.penalty),
                            fmt_money(g.total_pay)))
                return
