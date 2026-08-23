# -*- coding: utf-8 -*-
"""
Табель — учёт рабочего времени и выплат.
Windows-версия (Tkinter). Собирается в .exe через PyInstaller.
"""
import os
import sys
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "core"), os.path.join(HERE, "core")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from timecard_core import (THEME as T, DayEntry, Storage, Totals, WEEKDAYS_RU,
                           MONTHS_RU, parse_time, parse_duration, fmt_time, fmt_hm,
                           fmt_hm_short, fmt_money, week_start, week_range,
                           week_title, month_title, month_range)
import ui_kit as ui
from ui_kit import Card, Field, Toggle, StatTile, FONT, F_BODY, F_BODY_B, F_SMALL
import reports


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Табель — учёт рабочего времени и выплат")
        self.geometry("1180x760")
        self.minsize(1040, 700)
        self.configure(bg=T["bg"])
        try:
            self.iconbitmap(os.path.join(HERE, "assets", "icon.ico"))
        except Exception:
            pass

        self.db = Storage()
        self.current = dt.date.today()
        self._loading = False

        ui.install_styles(self)
        self._build_header()
        self._build_tabs()
        self.load_date(self.current)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-s>", lambda e: self.save_day())
        self.bind("<Prior>", lambda e: self.shift_day(-1))
        self.bind("<Next>", lambda e: self.shift_day(1))

    # ------------------------------------------------------------------ шапка
    def _build_header(self):
        head = tk.Frame(self, bg=T["accent"], height=74)
        head.pack(fill="x")
        head.pack_propagate(False)

        left = tk.Frame(head, bg=T["accent"])
        left.pack(side="left", padx=22)
        tk.Label(left, text="ТАБЕЛЬ", bg=T["accent"], fg="white",
                 font=(FONT, 18, "bold")).pack(anchor="w", pady=(14, 0))
        tk.Label(left, text="учёт рабочего времени и выплат", bg=T["accent"],
                 fg="#DCEBF8", font=F_SMALL).pack(anchor="w")

        right = tk.Frame(head, bg=T["accent"])
        right.pack(side="right", padx=22)
        self.lbl_today = tk.Label(right, bg=T["accent"], fg="white", font=(FONT, 11, "bold"))
        self.lbl_today.pack(anchor="e", pady=(16, 0))
        today = dt.date.today()
        self.lbl_today.config(text="Сегодня: %s, %d %s %d" % (
            WEEKDAYS_RU[today.weekday()], today.day,
            MONTHS_RU[today.month - 1].lower(), today.year))
        self.lbl_week_head = tk.Label(right, bg=T["accent"], fg="#DCEBF8", font=F_SMALL)
        self.lbl_week_head.pack(anchor="e")

    def _build_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(10, 12))
        self.tab_day = tk.Frame(self.nb, bg=T["bg"])
        self.tab_week = tk.Frame(self.nb, bg=T["bg"])
        self.tab_hist = tk.Frame(self.nb, bg=T["bg"])
        self.tab_set = tk.Frame(self.nb, bg=T["bg"])
        self.nb.add(self.tab_day, text="Рабочий день")
        self.nb.add(self.tab_week, text="Неделя")
        self.nb.add(self.tab_hist, text="История")
        self.nb.add(self.tab_set, text="Настройки")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)
        self._build_day_tab()
        self._build_week_tab()
        self._build_hist_tab()
        self._build_settings_tab()

    # ------------------------------------------------------------- вкладка ДЕНЬ
    def _build_day_tab(self):
        root = self.tab_day
        root.columnconfigure(0, weight=3, uniform="c")
        root.columnconfigure(1, weight=2, uniform="c")
        root.rowconfigure(1, weight=1)

        # --- строка выбора даты ---
        bar = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"],
                       highlightthickness=1)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(6, 10))
        ttk.Button(bar, text="◀", style="Nav.TButton",
                   command=lambda: self.shift_day(-1)).pack(side="left", padx=(10, 6), pady=8)
        self.lbl_wd = tk.Label(bar, bg=T["surface"], fg=T["accent_dark"],
                               font=(FONT, 15, "bold"))
        self.lbl_wd.pack(side="left", padx=(4, 10))
        self.lbl_date = tk.Label(bar, bg=T["surface"], fg=T["text"], font=(FONT, 13))
        self.lbl_date.pack(side="left")
        ttk.Button(bar, text="▶", style="Nav.TButton",
                   command=lambda: self.shift_day(1)).pack(side="left", padx=8)
        ttk.Button(bar, text="Сегодня", style="Ghost.TButton",
                   command=lambda: self.load_date(dt.date.today())).pack(side="left", padx=4)
        self.lbl_saved = tk.Label(bar, bg=T["surface"], fg=T["ok"], font=F_SMALL)
        self.lbl_saved.pack(side="right", padx=14)

        # --- левая колонка ---
        left = tk.Frame(root, bg=T["bg"])
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # время
        c_time = Card(left, "Время работы")
        c_time.grid(row=0, column=0, sticky="ew")
        b = c_time.body
        row = tk.Frame(b, bg=T["surface"])
        row.pack(fill="x")
        self.f_start = Field(row, "Начало работы", width=8, hint="8  или  8:00")
        self.f_start.pack(side="left", padx=(0, 14))
        self.f_end = Field(row, "Конец работы", width=8, hint="17:15  или  17.15")
        self.f_end.pack(side="left", padx=(0, 14))
        self.f_start.var.trace_add("write", lambda *a: self.recalc())
        self.f_end.var.trace_add("write", lambda *a: self.recalc())

        lunchbox = tk.Frame(b, bg=T["surface"])
        lunchbox.pack(fill="x", pady=(10, 0))
        self.t_lunch = Toggle(lunchbox, "Был обед (вычесть из времени)",
                              command=self.toggle_lunch)
        self.t_lunch.pack(anchor="w")
        self.lunch_panel = tk.Frame(b, bg=T["surface_alt"], highlightthickness=1,
                                    highlightbackground=T["border"])
        inner = tk.Frame(self.lunch_panel, bg=T["surface_alt"])
        inner.pack(fill="x", padx=12, pady=10)
        self.f_lunch = Field(inner, "Обед, минут", width=8, hint="30  •  45  •  1:00")
        self.f_lunch.configure(bg=T["surface_alt"])
        for ch in self.f_lunch.winfo_children():
            try:
                ch.configure(bg=T["surface_alt"])
            except tk.TclError:
                pass
        self.f_lunch.pack(side="left")
        self.f_lunch.var.trace_add("write", lambda *a: self.recalc())
        for m in ("30", "45", "60"):
            ttk.Button(inner, text=m + " мин", style="Ghost.TButton",
                       command=lambda v=m: (self.f_lunch.set(v), self.recalc())
                       ).pack(side="left", padx=(10, 0), pady=(12, 0))

        # работы
        c_work = Card(left, "Объём и качество произведённых работ")
        c_work.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.txt_works = tk.Text(c_work.body, height=5, font=(FONT, 11), wrap="word",
                                 bg=T["white"], fg=T["text"], relief="flat",
                                 highlightthickness=1, highlightbackground=T["border"],
                                 highlightcolor=T["accent"], padx=8, pady=6)
        self.txt_works.pack(fill="both", expand=True)

        # доп. работы
        c_extra = Card(left, "Дополнительные работы")
        c_extra.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        be = c_extra.body
        self.t_extra = Toggle(be, "Были дополнительные работы", command=self.toggle_extra)
        self.t_extra.pack(anchor="w")
        self.extra_panel = tk.Frame(be, bg=T["surface_alt"], highlightthickness=1,
                                    highlightbackground=T["border"])
        ei = tk.Frame(self.extra_panel, bg=T["surface_alt"])
        ei.pack(fill="x", padx=12, pady=10)

        r1 = tk.Frame(ei, bg=T["surface_alt"])
        r1.pack(fill="x")
        self.f_xstart = self._alt_field(r1, "Начало доп. работ", 8, "10:00")
        self.f_xend = self._alt_field(r1, "Конец доп. работ", 8, "16:30")
        self.f_xrate = self._alt_field(r1, "Ставка доп., ₽/час", 9, "своя ставка")
        for f in (self.f_xstart, self.f_xend, self.f_xrate):
            f.var.trace_add("write", lambda *a: self.recalc())

        r2 = tk.Frame(ei, bg=T["surface_alt"])
        r2.pack(fill="x", pady=(8, 0))
        self.t_xfixed = Toggle(r2, "Оплата фиксированной суммой (не по часам)",
                               command=self.recalc, bg=T["surface_alt"])
        self.t_xfixed.pack(anchor="w")
        self.f_xfixed = self._alt_field(r2, "Сумма за доп. работы, ₽", 12, "например 250")
        self.f_xfixed.var.trace_add("write", lambda *a: self.recalc())

        tk.Label(ei, text="Описание дополнительных работ", bg=T["surface_alt"],
                 fg=T["text_muted"], font=F_SMALL).pack(anchor="w", pady=(10, 2))
        self.txt_xworks = tk.Text(ei, height=2, font=(FONT, 10), wrap="word",
                                  bg=T["white"], fg=T["text"], relief="flat",
                                  highlightthickness=1, highlightbackground=T["border"],
                                  highlightcolor=T["accent"], padx=8, pady=4)
        self.txt_xworks.pack(fill="x")

        # --- правая колонка: расчёт ---
        right = tk.Frame(root, bg=T["bg"])
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        c_calc = Card(right, "Расчёт за день")
        c_calc.grid(row=0, column=0, sticky="ew")
        bc = c_calc.body

        g = tk.Frame(bc, bg=T["surface"])
        g.pack(fill="x")
        g.columnconfigure((0, 1), weight=1, uniform="t")
        self.tile_hours = StatTile(g, "Отработано (основное)", "0 ч 00 мин")
        self.tile_hours.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=4)
        self.tile_xhours = StatTile(g, "Дополнительно", "0 ч 00 мин")
        self.tile_xhours.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=4)

        tk.Frame(bc, bg=T["accent_light"], height=1).pack(fill="x", pady=10)

        self.rows_money = {}
        for key, label in (("day", "Оплата за день"),
                           ("extra", "Доп. работы"),
                           ("bonus", "Премия")):
            r = tk.Frame(bc, bg=T["surface"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label, bg=T["surface"], fg=T["text"],
                     font=F_BODY).pack(side="left")
            v = tk.Label(r, text="0 ₽", bg=T["surface"], fg=T["text"], font=(FONT, 12, "bold"))
            v.pack(side="right")
            self.rows_money[key] = v

        rb = tk.Frame(bc, bg=T["surface"])
        rb.pack(fill="x", pady=(6, 0))
        tk.Label(rb, text="Премия за день, ₽", bg=T["surface"], fg=T["text_muted"],
                 font=F_SMALL).pack(side="left")
        self.f_bonus = Field(bc, "", width=12, justify="right")
        self.f_bonus.pack(fill="x")
        self.f_bonus.var.trace_add("write", lambda *a: self.recalc())

        tk.Frame(bc, bg=T["accent_light"], height=2).pack(fill="x", pady=10)
        tot = tk.Frame(bc, bg=T["surface"])
        tot.pack(fill="x")
        tk.Label(tot, text="ИТОГО ЗА ДЕНЬ", bg=T["surface"], fg=T["accent_dark"],
                 font=F_BODY_B).pack(side="left")
        self.lbl_total_day = tk.Label(tot, text="0 ₽", bg=T["surface"], fg=T["ok"],
                                      font=(FONT, 20, "bold"))
        self.lbl_total_day.pack(side="right")

        # кнопки
        c_act = Card(right)
        c_act.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        pad = tk.Frame(c_act, bg=T["surface"])
        pad.pack(fill="x", padx=14, pady=12)
        ttk.Button(pad, text="СОХРАНИТЬ ДЕНЬ   (Ctrl+S)", style="Accent.TButton",
                   command=self.save_day).pack(fill="x")
        row2 = tk.Frame(pad, bg=T["surface"])
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text="Заполнить по умолчанию", style="Ghost.TButton",
                   command=self.fill_defaults).pack(side="left", expand=True, fill="x",
                                                    padx=(0, 4))
        ttk.Button(row2, text="Очистить день", style="Danger.TButton",
                   command=self.clear_day).pack(side="left", expand=True, fill="x",
                                                padx=(4, 0))

        # мини-итог недели
        c_wk = Card(right, "Текущая неделя")
        c_wk.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.lbl_wk_range = tk.Label(c_wk.body, bg=T["surface"], fg=T["text_muted"],
                                     font=F_SMALL)
        self.lbl_wk_range.pack(anchor="w")
        self.wk_mini = tk.Frame(c_wk.body, bg=T["surface"])
        self.wk_mini.pack(fill="both", expand=True, pady=(6, 0))

    def _alt_field(self, parent, label, width, hint):
        f = Field(parent, label, width=width, hint=hint)
        f.configure(bg=T["surface_alt"])
        for ch in f.winfo_children():
            try:
                ch.configure(bg=T["surface_alt"])
            except tk.TclError:
                pass
        f.pack(side="left", padx=(0, 14))
        return f

    # ----------------------------------------------------------- вкладка НЕДЕЛЯ
    def _build_week_tab(self):
        root = self.tab_week
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        bar = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"],
                       highlightthickness=1)
        bar.grid(row=0, column=0, sticky="ew", pady=(6, 10))
        ttk.Button(bar, text="◀", style="Nav.TButton",
                   command=lambda: self.shift_week(-1)).pack(side="left", padx=(10, 6), pady=8)
        self.lbl_week = tk.Label(bar, bg=T["surface"], fg=T["accent_dark"],
                                 font=(FONT, 14, "bold"))
        self.lbl_week.pack(side="left", padx=8)
        ttk.Button(bar, text="▶", style="Nav.TButton",
                   command=lambda: self.shift_week(1)).pack(side="left", padx=6)
        ttk.Button(bar, text="Текущая неделя", style="Ghost.TButton",
                   command=lambda: self.load_date(dt.date.today())).pack(side="left")
        ttk.Button(bar, text="Excel: неделя", style="Ghost.TButton",
                   command=lambda: self.export("week", "xlsx")).pack(side="right", padx=(4, 10))
        ttk.Button(bar, text="PDF: неделя", style="Ghost.TButton",
                   command=lambda: self.export("week", "pdf")).pack(side="right", padx=4)
        ttk.Button(bar, text="Карточка за месяц (PDF)", style="Accent.TButton",
                   command=lambda: self.export("month", "pdf")).pack(side="right", padx=4)

        cols = ("wd", "date", "time", "hours", "xtime", "xhours", "works",
                "pay", "xpay", "bonus", "total")
        titles = ("День", "Дата", "Время работы", "Кол-во часов", "Доп. время",
                  "Доп. часы", "Объём и качество работ", "Оплата за день",
                  "Доп. работы", "Премия", "Итого")
        widths = (46, 74, 118, 96, 108, 84, 330, 112, 100, 84, 110)
        wrap = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"],
                        highlightthickness=1)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for c, t, w in zip(cols, titles, widths):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c != "works" else "w",
                             stretch=(c == "works"))
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.tag_configure("weekend", background="#EDF3F9", foreground=T["text_muted"])
        self.tree.tag_configure("today", background=T["accent_light"], font=F_BODY_B)
        self.tree.tag_configure("total", background="#D6E6F4", font=(FONT, 10, "bold"))
        self.tree.bind("<Double-1>", self._tree_open_day)

        foot = tk.Frame(root, bg=T["bg"])
        foot.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        foot.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="f")
        self.w_tiles = {}
        for i, (k, lab, col) in enumerate([
                ("days", "Отработано дней", None),
                ("hours", "Основных часов", None),
                ("xhours", "Доп. часов", None),
                ("bonus", "Премии", None),
                ("total", "ИТОГО К ВЫПЛАТЕ", T["ok"])]):
            t = StatTile(foot, lab, "—", color=col, bg=T["surface"])
            t.grid(row=0, column=i, sticky="ew", padx=4)
            self.w_tiles[k] = t

    # --------------------------------------------------------- вкладка ИСТОРИЯ
    def _build_hist_tab(self):
        root = self.tab_hist
        root.rowconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)

        side = Card(root, "Месяцы")
        side.grid(row=0, column=0, sticky="nsw", pady=6, padx=(0, 10))
        self.lst_months = tk.Listbox(side.body, width=22, font=F_BODY, bd=0,
                                     bg=T["white"], fg=T["text"], relief="flat",
                                     highlightthickness=1,
                                     highlightbackground=T["border"],
                                     selectbackground=T["accent"],
                                     selectforeground="white", activestyle="none")
        self.lst_months.pack(fill="both", expand=True, ipady=4)
        self.lst_months.bind("<<ListboxSelect>>", self._hist_pick)
        ttk.Button(side.body, text="Excel: месяц", style="Ghost.TButton",
                   command=lambda: self.export("month", "xlsx")).pack(fill="x", pady=(8, 0))
        ttk.Button(side.body, text="PDF: месяц", style="Ghost.TButton",
                   command=lambda: self.export("month", "pdf")).pack(fill="x", pady=4)

        main = Card(root, "Записи месяца")
        main.grid(row=0, column=1, sticky="nsew", pady=6)
        cols = ("date", "wd", "time", "hours", "xhours", "works", "total")
        titles = ("Дата", "День", "Время", "Часы", "Доп.", "Работы", "Итого, ₽")
        widths = (92, 50, 120, 80, 74, 420, 110)
        self.htree = ttk.Treeview(main.body, columns=cols, show="headings")
        for c, t, w in zip(cols, titles, widths):
            self.htree.heading(c, text=t)
            self.htree.column(c, width=w, anchor="center" if c != "works" else "w",
                              stretch=(c == "works"))
        vs = ttk.Scrollbar(main.body, orient="vertical", command=self.htree.yview)
        self.htree.configure(yscrollcommand=vs.set)
        self.htree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.htree.tag_configure("odd", background="#F7FAFD")
        self.htree.tag_configure("wtotal", background="#E3EDF7", font=F_BODY_B)
        self.htree.tag_configure("mtotal", background="#C9DFF2", font=(FONT, 11, "bold"))
        self.htree.bind("<Double-1>", self._htree_open_day)

    # ------------------------------------------------------- вкладка НАСТРОЙКИ
    def _build_settings_tab(self):
        root = self.tab_set
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)

        c1 = Card(root, "Оплата")
        c1.grid(row=0, column=0, sticky="new", pady=6, padx=(0, 8))
        b = c1.body
        self.s_rate = Field(b, "Ставка за час основной работы, ₽", width=14, justify="left")
        self.s_rate.pack(fill="x", pady=4)
        self.s_xrate = Field(b, "Ставка за час доп. работ, ₽", width=14, justify="left")
        self.s_xrate.pack(fill="x", pady=4)

        c2 = Card(root, "Значения по умолчанию для нового дня")
        c2.grid(row=0, column=1, sticky="new", pady=6)
        b2 = c2.body
        self.s_start = Field(b2, "Начало работы", width=10, justify="left")
        self.s_start.pack(fill="x", pady=4)
        self.s_end = Field(b2, "Конец работы", width=10, justify="left")
        self.s_end.pack(fill="x", pady=4)
        self.s_lunch = Field(b2, "Обед по умолчанию, минут", width=10, justify="left")
        self.s_lunch.pack(fill="x", pady=4)

        c3 = Card(root, "Данные для отчётов")
        c3.grid(row=1, column=0, sticky="new", pady=6, padx=(0, 8))
        self.s_emp = Field(c3.body, "Ф. И. О. работника", width=30, justify="left")
        self.s_emp.pack(fill="x", pady=4)
        self.s_org = Field(c3.body, "Организация / участок", width=30, justify="left")
        self.s_org.pack(fill="x", pady=4)
        ttk.Button(c3.body, text="СОХРАНИТЬ НАСТРОЙКИ", style="Accent.TButton",
                   command=self.save_settings).pack(fill="x", pady=(12, 0))

        c4 = Card(root, "Данные и резервные копии")
        c4.grid(row=1, column=1, sticky="new", pady=6)
        tk.Label(c4.body, text="База данных:", bg=T["surface"], fg=T["text_muted"],
                 font=F_SMALL).pack(anchor="w")
        tk.Label(c4.body, text=self.db.path, bg=T["surface"], fg=T["text"],
                 font=("Consolas", 8), wraplength=430, justify="left").pack(anchor="w",
                                                                           pady=(0, 10))
        ttk.Button(c4.body, text="Сохранить резервную копию (.json)", style="Ghost.TButton",
                   command=self.backup).pack(fill="x", pady=3)
        ttk.Button(c4.body, text="Восстановить из копии (.json)", style="Ghost.TButton",
                   command=self.restore).pack(fill="x", pady=3)
        ttk.Button(c4.body, text="Открыть папку с данными", style="Ghost.TButton",
                   command=self.open_folder).pack(fill="x", pady=3)

        self.load_settings()

    # --------------------------------------------------------------- поведение
    def toggle_lunch(self):
        if self.t_lunch.get():
            self.lunch_panel.pack(fill="x", pady=(6, 0))
            if not self.f_lunch.get().strip():
                self.f_lunch.set(self.db.get("default_lunch", "60"))
        else:
            self.lunch_panel.pack_forget()
        self.recalc()

    def toggle_extra(self):
        if self.t_extra.get():
            self.extra_panel.pack(fill="x", pady=(6, 0))
            if not self.f_xrate.get().strip():
                self.f_xrate.set(self.db.get("extra_rate", "250"))
        else:
            self.extra_panel.pack_forget()
        self.recalc()

    def collect(self):
        """Собрать DayEntry из полей формы."""
        e = DayEntry(date=self.current.isoformat())
        e.start = parse_time(self.f_start.get())
        e.end = parse_time(self.f_end.get())
        e.lunch_on = self.t_lunch.get()
        e.lunch_min = parse_duration(self.f_lunch.get()) if e.lunch_on else 0
        e.works = self.txt_works.get("1.0", "end").strip()
        e.extra_on = self.t_extra.get()
        e.extra_start = parse_time(self.f_xstart.get())
        e.extra_end = parse_time(self.f_xend.get())
        e.extra_works = self.txt_xworks.get("1.0", "end").strip()
        e.extra_use_fixed = self.t_xfixed.get()
        e.extra_rate = _f(self.f_xrate.get(), self.db.get_float("extra_rate", 250))
        e.extra_fixed = _f(self.f_xfixed.get(), 0)
        e.bonus = _f(self.f_bonus.get(), 0)
        e.rate = self.db.get_float("rate", 250)
        return e

    def recalc(self, *_):
        if self._loading:
            return
        e = self.collect()
        self.tile_hours.set(fmt_hm(e.work_min))
        self.tile_xhours.set(fmt_hm(e.extra_min))
        self.rows_money["day"].config(text=fmt_money(e.day_pay))
        self.rows_money["extra"].config(text=fmt_money(e.extra_pay))
        self.rows_money["bonus"].config(text=fmt_money(e.bonus))
        self.lbl_total_day.config(text=fmt_money(e.total_pay))

    def load_date(self, d):
        self._loading = True
        self.current = d
        e = self.db.load_day(d)
        self.lbl_wd.config(text=WEEKDAYS_RU[d.weekday()])
        self.lbl_date.config(text="%02d.%02d.%d" % (d.day, d.month, d.year))
        self.lbl_week_head.config(text="Неделя: " + week_title(d))
        self.lbl_saved.config(text="● запись сохранена" if not e.is_empty else "")

        self.f_start.set(fmt_time(e.start) if e.start is not None else "")
        self.f_end.set(fmt_time(e.end) if e.end is not None else "")
        self.t_lunch.set(e.lunch_on)
        self.f_lunch.set(e.lunch_min or "")
        self.txt_works.delete("1.0", "end")
        self.txt_works.insert("1.0", e.works)
        self.t_extra.set(e.extra_on)
        self.f_xstart.set(fmt_time(e.extra_start) if e.extra_start is not None else "")
        self.f_xend.set(fmt_time(e.extra_end) if e.extra_end is not None else "")
        self.f_xrate.set(_num(e.extra_rate))
        self.t_xfixed.set(e.extra_use_fixed)
        self.f_xfixed.set(_num(e.extra_fixed) if e.extra_fixed else "")
        self.txt_xworks.delete("1.0", "end")
        self.txt_xworks.insert("1.0", e.extra_works)
        self.f_bonus.set(_num(e.bonus) if e.bonus else "")

        self.lunch_panel.pack_forget()
        self.extra_panel.pack_forget()
        if e.lunch_on:
            self.lunch_panel.pack(fill="x", pady=(6, 0))
        if e.extra_on:
            self.extra_panel.pack(fill="x", pady=(6, 0))

        self._loading = False
        self.recalc()
        self.refresh_week()

    def shift_day(self, n):
        self.load_date(self.current + dt.timedelta(days=n))

    def shift_week(self, n):
        self.load_date(self.current + dt.timedelta(weeks=n))

    def fill_defaults(self):
        self.f_start.set(self.db.get("default_start", "8:00"))
        self.f_end.set(self.db.get("default_end", "17:00"))
        self.recalc()

    def save_day(self):
        e = self.collect()
        if e.start is not None and e.end is None:
            messagebox.showwarning("Не хватает данных", "Укажите время окончания работы.")
            return
        if e.extra_on and (e.extra_start is None or e.extra_end is None) \
                and not e.extra_use_fixed:
            messagebox.showwarning("Дополнительные работы",
                                   "Укажите начало и конец доп. работ "
                                   "или включите оплату фиксированной суммой.")
            return
        self.db.save_day(e)
        self.lbl_saved.config(text="● сохранено " + dt.datetime.now().strftime("%H:%M:%S"))
        ui.toast(self, "День %02d.%02d сохранён — %s" % (
            self.current.day, self.current.month, fmt_money(e.total_pay)))
        self.refresh_week()
        self.refresh_history()

    def clear_day(self):
        if messagebox.askyesno("Очистить день",
                               "Удалить запись за %02d.%02d.%d?" % (
                                   self.current.day, self.current.month, self.current.year)):
            self.db.delete_day(self.current)
            self.load_date(self.current)
            ui.toast(self, "Запись удалена", "warn")

    def _tree_open_day(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid.startswith("d:"):
            self.load_date(dt.date.fromisoformat(iid[2:]))
            self.nb.select(self.tab_day)

    def _htree_open_day(self, _e):
        sel = self.htree.selection()
        if sel and sel[0].startswith("d:"):
            self.load_date(dt.date.fromisoformat(sel[0][2:]))
            self.nb.select(self.tab_day)

    # ------------------------------------------------------------- обновление
    def refresh_week(self):
        days = self.db.week_days(self.current)
        self.lbl_week.config(text=week_title(self.current))
        a, b = week_range(self.current)
        self.lbl_wk_range.config(text="Понедельник — воскресенье: " + week_title(self.current))

        self.tree.delete(*self.tree.get_children())
        today = dt.date.today()
        for i, e in enumerate(days):
            d = e.date_obj
            tags = []
            if d == today:
                tags.append("today")
            elif d.weekday() >= 5:
                tags.append("weekend")
            elif i % 2:
                tags.append("odd")
            time_s = ("%s — %s" % (fmt_time(e.start), fmt_time(e.end))
                      if e.start is not None and e.end is not None else "—")
            if e.lunch_on and e.lunch_min:
                time_s += "  (−%dм)" % e.lunch_min
            xt = ("%s — %s" % (fmt_time(e.extra_start), fmt_time(e.extra_end))
                  if e.extra_on and e.extra_start is not None and e.extra_end is not None
                  else ("сумма" if e.extra_on and e.extra_use_fixed else "—"))
            self.tree.insert("", "end", iid="d:" + e.date, tags=tags, values=(
                ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                "%02d.%02d" % (d.day, d.month),
                time_s,
                fmt_hm_short(e.work_min) if e.work_min else "—",
                xt,
                fmt_hm_short(e.extra_min) if e.extra_min else "—",
                (e.works.replace("\n", " ")[:120] or "—"),
                fmt_money(e.day_pay) if e.day_pay else "—",
                fmt_money(e.extra_pay) if e.extra_pay else "—",
                fmt_money(e.bonus) if e.bonus else "—",
                fmt_money(e.total_pay) if e.total_pay else "—",
            ))
        t = Totals(days)
        self.tree.insert("", "end", iid="total", tags=("total",), values=(
            "", "ИТОГО", "", fmt_hm_short(t.work_min), "", fmt_hm_short(t.extra_min),
            "Отработано дней: %d   •   всего %s" % (t.worked_days, fmt_hm(t.total_min)),
            fmt_money(t.day_pay), fmt_money(t.extra_pay), fmt_money(t.bonus),
            fmt_money(t.total_pay)))

        self.w_tiles["days"].set(str(t.worked_days))
        self.w_tiles["hours"].set(fmt_hm(t.work_min))
        self.w_tiles["xhours"].set(fmt_hm(t.extra_min))
        self.w_tiles["bonus"].set(fmt_money(t.bonus))
        self.w_tiles["total"].set(fmt_money(t.total_pay))

        for w in self.wk_mini.winfo_children():
            w.destroy()
        for e in days:
            d = e.date_obj
            r = tk.Frame(self.wk_mini, bg=T["surface"])
            r.pack(fill="x", pady=1)
            nm = "%s %02d.%02d" % (["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                                   d.day, d.month)
            fg = T["accent_dark"] if d == self.current else (
                T["text_muted"] if e.is_empty else T["text"])
            tk.Label(r, text=nm, bg=T["surface"], fg=fg,
                     font=F_BODY_B if d == self.current else F_BODY).pack(side="left")
            tk.Label(r, text=(fmt_money(e.total_pay) if not e.is_empty else "—"),
                     bg=T["surface"], fg=fg, font=F_BODY).pack(side="right")
            tk.Label(r, text=(fmt_hm_short(e.total_min) if not e.is_empty else ""),
                     bg=T["surface"], fg=T["text_muted"], font=F_SMALL).pack(side="right",
                                                                             padx=10)
        sep = tk.Frame(self.wk_mini, bg=T["accent_light"], height=2)
        sep.pack(fill="x", pady=6)
        r = tk.Frame(self.wk_mini, bg=T["surface"])
        r.pack(fill="x")
        tk.Label(r, text="За неделю", bg=T["surface"], fg=T["accent_dark"],
                 font=F_BODY_B).pack(side="left")
        tk.Label(r, text=fmt_money(t.total_pay), bg=T["surface"], fg=T["ok"],
                 font=(FONT, 13, "bold")).pack(side="right")

    def refresh_history(self):
        months = self.db.filled_months()
        cur = self.current.strftime("%Y-%m")
        if cur not in months:
            months = [cur] + months
        self.lst_months.delete(0, "end")
        self._months = months
        for m in months:
            y, mm = m.split("-")
            self.lst_months.insert("end", "  %s %s" % (MONTHS_RU[int(mm) - 1], y))
        if cur in months:
            i = months.index(cur)
            self.lst_months.selection_clear(0, "end")
            self.lst_months.selection_set(i)
        self._fill_history(self.current)

    def _hist_pick(self, _e):
        sel = self.lst_months.curselection()
        if not sel:
            return
        y, m = self._months[sel[0]].split("-")
        self._fill_history(dt.date(int(y), int(m), 1))

    def _fill_history(self, anchor):
        self.htree.delete(*self.htree.get_children())
        days = self.db.month_days(anchor)
        wk_buf, i = [], 0
        for e in days:
            d = e.date_obj
            if not e.is_empty:
                self.htree.insert("", "end", iid="d:" + e.date,
                                  tags=("odd",) if i % 2 else (), values=(
                    "%02d.%02d.%d" % (d.day, d.month, d.year),
                    ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                    "%s — %s" % (fmt_time(e.start), fmt_time(e.end))
                    if e.start is not None and e.end is not None else "—",
                    fmt_hm_short(e.work_min),
                    fmt_hm_short(e.extra_min) if e.extra_min else "—",
                    e.works.replace("\n", " ")[:150],
                    fmt_money(e.total_pay)))
                i += 1
            wk_buf.append(e)
            if d.weekday() == 6 or d == days[-1].date_obj:
                t = Totals(wk_buf)
                if t.worked_days:
                    self.htree.insert("", "end", tags=("wtotal",), values=(
                        "", "", "Итого за неделю", fmt_hm_short(t.work_min),
                        fmt_hm_short(t.extra_min),
                        "дней: %d" % t.worked_days, fmt_money(t.total_pay)))
                wk_buf = []
        mt = Totals(days)
        self.htree.insert("", "end", tags=("mtotal",), values=(
            "", "", "ИТОГО ЗА %s" % month_title(anchor).upper(),
            fmt_hm_short(mt.work_min), fmt_hm_short(mt.extra_min),
            "оплата %s + доп %s + премия %s" % (fmt_money(mt.day_pay),
                                                fmt_money(mt.extra_pay),
                                                fmt_money(mt.bonus)),
            fmt_money(mt.total_pay)))
        self._hist_anchor = anchor

    def _on_tab(self, _e):
        try:
            tab = self.nb.index(self.nb.select())
        except tk.TclError:
            return
        if tab == 1:
            self.refresh_week()
        elif tab == 2:
            self.refresh_history()

    # ------------------------------------------------------------- настройки
    def load_settings(self):
        self.s_rate.set(self.db.get("rate", "250"))
        self.s_xrate.set(self.db.get("extra_rate", "250"))
        self.s_start.set(self.db.get("default_start", "8:00"))
        self.s_end.set(self.db.get("default_end", "17:00"))
        self.s_lunch.set(self.db.get("default_lunch", "60"))
        self.s_emp.set(self.db.get("employee", ""))
        self.s_org.set(self.db.get("organization", ""))

    def save_settings(self):
        self.db.set("rate", _f(self.s_rate.get(), 250))
        self.db.set("extra_rate", _f(self.s_xrate.get(), 250))
        self.db.set("default_start", self.s_start.get() or "8:00")
        self.db.set("default_end", self.s_end.get() or "17:00")
        self.db.set("default_lunch", self.s_lunch.get() or "60")
        self.db.set("employee", self.s_emp.get())
        self.db.set("organization", self.s_org.get())
        ui.toast(self, "Настройки сохранены")
        self.recalc()
        self.refresh_week()

    def backup(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("Резервная копия", "*.json")],
            initialfile="tabel_backup_%s.json" % dt.date.today().isoformat())
        if p:
            self.db.export_json(p)
            ui.toast(self, "Копия сохранена")

    def restore(self):
        p = filedialog.askopenfilename(filetypes=[("Резервная копия", "*.json")])
        if p and messagebox.askyesno("Восстановление",
                                     "Записи из файла будут добавлены/перезаписаны. Продолжить?"):
            n = self.db.import_json(p)
            self.load_date(self.current)
            self.refresh_history()
            ui.toast(self, "Восстановлено записей: %d" % n)

    def open_folder(self):
        folder = os.path.dirname(self.db.path)
        try:
            os.startfile(folder)          # Windows
        except AttributeError:
            os.system('xdg-open "%s"' % folder)

    # --------------------------------------------------------------- экспорт
    def export(self, period, fmt):
        if period == "week":
            a, b = week_range(self.current)
            title = "Неделя " + week_title(self.current)
            name = "tabel_nedelya_%s" % a.isoformat()
        else:
            anchor = getattr(self, "_hist_anchor", self.current)
            a, b = month_range(anchor)
            title = "Карточка учёта рабочего времени и выплат за %s" % month_title(anchor)
            name = "tabel_%s" % anchor.strftime("%Y-%m")
        days = self.db.range_days(a, b)
        ext = ".xlsx" if fmt == "xlsx" else ".pdf"
        path = filedialog.asksaveasfilename(defaultextension=ext, initialfile=name + ext,
                                            filetypes=[(ext[1:].upper(), "*" + ext)])
        if not path:
            return
        meta = {"employee": self.db.get("employee", ""),
                "organization": self.db.get("organization", ""),
                "rate": self.db.get("rate", "250"),
                "period": period}
        try:
            if fmt == "xlsx":
                reports.export_xlsx(path, title, days, meta)
            else:
                reports.export_pdf(path, title, days, meta)
        except ImportError as ex:
            messagebox.showerror("Нет библиотеки", str(ex))
            return
        ui.toast(self, "Файл сохранён")
        if messagebox.askyesno("Готово", "Файл сохранён.\nОткрыть его сейчас?"):
            try:
                os.startfile(path)
            except AttributeError:
                os.system('xdg-open "%s"' % path)

    def _on_close(self):
        try:
            e = self.collect()
            if not e.is_empty:
                self.db.save_day(e)
        except Exception:
            pass
        self.db.close()
        self.destroy()


def _f(text, default=0.0):
    try:
        return float(str(text).replace(",", ".").replace(" ", "").replace("\u20bd", ""))
    except (TypeError, ValueError):
        return default


def _num(v):
    v = float(v or 0)
    return str(int(v)) if abs(v - int(v)) < 1e-9 else ("%.2f" % v)


if __name__ == "__main__":
    App().mainloop()
