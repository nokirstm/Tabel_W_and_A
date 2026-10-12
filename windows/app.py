# -*- coding: utf-8 -*-
"""Табель — учёт рабочего времени и выплат. Windows-версия (Tkinter). ВЕРСИЯ 2.0.2"""
import os
import sys
import json
import queue
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "core"), os.path.join(HERE, "core")):
    if os.path.isdir(p) and p not in sys.path: sys.path.insert(0, p)

from timecard_core import (THEME as T, DayEntry, Storage, Totals, WEEKDAYS_RU, MONTHS_RU,
                           parse_time, parse_duration, fmt_time, fmt_hm, fmt_hm_short,
                           fmt_money, week_start, week_range, week_title, month_title, month_range)
import ui_kit as ui
from ui_kit import Card, Field, Toggle, StatTile, FONT, F_BODY, F_BODY_B, F_SMALL, F_GIANT

try:
    from sync_client import SyncClient
    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False

SYNC_API_URL = "https://script.google.com/macros/s/AKfycbwDWAS8t__5y3WdFudGQa8OMyWxxBYl56tiJY5RHjR1EmBPiyTrlXUpa2CcmI-q3sQBdQ/exec"
SYNC_API_TOKEN = "28096b2395454f05a7ce7a2b0fcfe3b2e58fd9bed8d5465db4560056a662659c"
APPROVED_COLOR = "#249d07"
POLL_MS = 30000
QUEUE_MS = 100

def _asset(name):
    bases = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass: bases.append(os.path.join(meipass, "assets"))
        bases.append(os.path.join(os.path.dirname(sys.executable), "assets"))
    bases.append(os.path.join(HERE, "assets"))
    for b in bases:
        p = os.path.join(b, name)
        if os.path.exists(p): return p
    return os.path.join(bases[0], name)

def _parse_date_ru(text):
    s = str(text or "").strip().replace("/", ".").replace("-", ".").replace("  ", " ")
    if not s: return None
    parts = s.split(".")
    if len(parts) != 3: return None
    if not all(p.isascii() and p.isdigit() for p in parts): return None
    d_s, m_s, y_s = parts
    if len(y_s) == 2: y_s = ("20" if int(y_s) < 70 else "19") + y_s
    if not (len(d_s) in (1, 2) and len(m_s) in (1, 2) and len(y_s) == 4): return None
    try: return dt.date(int(y_s), int(m_s), int(d_s))
    except ValueError: return None

def _fmt_date_ru(iso):
    try:
        d = dt.date.fromisoformat(str(iso))
        return "%02d.%02d.%d" % (d.day, d.month, d.year)
    except (TypeError, ValueError): return ""

# ================= ДИАЛОГИ =================

class RegDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        app._reg_dialog = self
        self.title("Первичная регистрация")
        self.resizable(False, False)
        self.transient(app)
        self.configure(bg=T["surface"])
        pad = tk.Frame(self, bg=T["surface"])
        pad.pack(fill="both", padx=20, pady=18)
        
        tk.Label(pad, text="Регистрация", bg=T["surface"], fg=T["accent_dark"], font=ui.F_H1).pack(anchor="w")
        tk.Label(pad, text="Выберите роль и укажите данные для создания аккаунта.", bg=T["surface"], fg=T["text_muted"], font=F_SMALL, wraplength=420, justify="left").pack(anchor="w", pady=(6, 12))
        
        self.role_var = tk.StringVar(value="employee")
        role_frame = tk.Frame(pad, bg=T["surface"])
        role_frame.pack(fill="x", pady=(0, 12))
        tk.Radiobutton(role_frame, text="Сотрудник", variable=self.role_var, value="employee", bg=T["surface"], font=F_BODY_B, anchor="w").pack(side="left", padx=(0, 20))
        tk.Radiobutton(role_frame, text="Руководитель", variable=self.role_var, value="manager", bg=T["surface"], font=F_BODY_B, anchor="w").pack(side="left")

        self.f_name = Field(pad, "Ф. И. О.", width=36, justify="left")
        self.f_name.pack(fill="x")
        self.f_birth = Field(pad, "Дата рождения", width=14, hint="ДД.ММ.ГГГГ")
        self.f_birth.pack(fill="x", pady=(10, 0))
        
        self.lbl_err = tk.Label(pad, text="", bg=T["surface"], fg=T["danger"], font=F_SMALL, wraplength=420, justify="left")
        self.lbl_err.pack(anchor="w", pady=(10, 0))
        
        row = tk.Frame(pad, bg=T["surface"])
        row.pack(fill="x", pady=(12, 0))
        self.btn_ok = ttk.Button(row, text="Зарегистрировать", style="Accent.TButton", command=self.submit)
        self.btn_ok.pack(side="left")
        ttk.Button(row, text="Позже", style="Ghost.TButton", command=self.destroy).pack(side="left", padx=(10, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def submit(self):
        name = self.f_name.get().strip()
        birth = _parse_date_ru(self.f_birth.get())
        if not name: return self.show_error("Укажите Ф. И. О.")
        if birth is None: return self.show_error("Дата рождения — в формате ДД.ММ.ГГГГ.")
        
        self.btn_ok.config(state="disabled")
        self.lbl_err.config(text="Отправка на сервер…", fg=T["text_muted"])
        role = self.role_var.get()
        self.app.db.set("role", role)
        
        if role == "manager":
            self.app.sync_client.send_async("create_manager", name, birth.isoformat(), callback=lambda r: self.app.sync_queue.put(("create_manager", r, name)))
        else:
            self.app.sync_client.send_async("create_account", name, birth.isoformat(), callback=lambda r: self.app.sync_queue.put(("create", r, name)))

    def show_error(self, text):
        self.lbl_err.config(text=text, fg=T["danger"])
        self.btn_ok.config(state="normal")

    def destroy(self):
        if getattr(self.app, "_reg_dialog", None) is self: self.app._reg_dialog = None
        super().destroy()

class CreateEmployeeDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Добавить сотрудника")
        self.resizable(False, False)
        self.transient(app)
        self.configure(bg=T["surface"])
        pad = tk.Frame(self, bg=T["surface"])
        pad.pack(fill="both", padx=20, pady=18)
        
        tk.Label(pad, text="Новый сотрудник", bg=T["surface"], fg=T["accent_dark"], font=ui.F_H2).pack(anchor="w")
        self.f_name = Field(pad, "Ф. И. О. сотрудника", width=36, justify="left")
        self.f_name.pack(fill="x", pady=(10, 0))
        self.f_birth = Field(pad, "Дата рождения", width=14, hint="ДД.ММ.ГГГГ")
        self.f_birth.pack(fill="x", pady=(10, 0))
        
        self.lbl_err = tk.Label(pad, text="", bg=T["surface"], fg=T["danger"], font=F_SMALL)
        self.lbl_err.pack(anchor="w", pady=(8, 0))
        
        row = tk.Frame(pad, bg=T["surface"])
        row.pack(fill="x", pady=(12, 0))
        self.btn_ok = ttk.Button(row, text="Создать", style="Accent.TButton", command=self.submit)
        self.btn_ok.pack(side="left")
        ttk.Button(row, text="Отмена", style="Ghost.TButton", command=self.destroy).pack(side="left", padx=(10, 0))

    def submit(self):
        name = self.f_name.get().strip()
        birth = _parse_date_ru(self.f_birth.get())
        if not name or birth is None: return self.lbl_err.config(text="Заполните ФИО и дату рождения (ДД.ММ.ГГГГ)", fg=T["danger"])
        
        self.btn_ok.config(state="disabled")
        mgr_id = self.app.db.get("manager_id", "")
        mgr_tok = self.app.db.get("manager_token", "")
        self.app.sync_client.send_async("create_employee", mgr_id, mgr_tok, name, birth.isoformat(), callback=lambda r: self.app.sync_queue.put(("create_emp", r, name)))

    def destroy(self):
        super().destroy()

class TokenDialog(tk.Toplevel):
    def __init__(self, app, token):
        super().__init__(app)
        self.app = app
        self.token = token
        self.title("Токен")
        self.resizable(False, False)
        self.transient(app)
        self.configure(bg=T["surface"])
        pad = tk.Frame(self, bg=T["surface"])
        pad.pack(fill="both", padx=20, pady=18)
        tk.Label(pad, text="Токен для привязки на телефоне:", bg=T["surface"], fg=T["accent_dark"], font=ui.F_H2).pack(anchor="w")
        self.ent = tk.Entry(pad, font=("Consolas", 14), justify="center", bg=T["white"], fg=T["text"], relief="flat", highlightthickness=1, highlightbackground=T["border"], state="readonly", readonlybackground=T["white"])
        self.ent.pack(fill="x", ipady=8, pady=(10, 0))
        self.ent.config(state="normal")
        self.ent.insert(0, token)
        self.ent.config(state="readonly")
        row = tk.Frame(pad, bg=T["surface"])
        row.pack(fill="x", pady=(14, 0))
        ttk.Button(row, text="Скопировать", style="Accent.TButton", command=lambda: [self.clipboard_clear(), self.clipboard_append(token), ui.toast(self.app, "Скопировано")]).pack(side="left")
        ttk.Button(row, text="Закрыть", style="Ghost.TButton", command=self.destroy).pack(side="left", padx=(10, 0))

# ================= ОСНОВНОЕ ПРИЛОЖЕНИЕ =================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Табель 2.0")
        self.geometry("1200x800")
        self.minsize(1100, 700)
        self.configure(bg=T["bg"])
        
        self.db = Storage()
        self.current = dt.date.today()
        self._loading = False
        self._locked = False
        self._reg_dialog = None
        self._sync_last_error = ""
        self._after_poll = None
        self._after_queue = None
        
        self.sync_queue = queue.Queue()
        self.sync_client = None
        if SYNC_AVAILABLE:
            dev_file = os.path.join(os.path.dirname(self.db.path), "device_id.txt")
            self.sync_client = SyncClient(SYNC_API_URL, SYNC_API_TOKEN, dev_file)
            emp_id, emp_tok = self._creds()
            if emp_id and emp_tok: self.sync_client.set_credentials(emp_id, emp_tok)
            
        self.sync_stats = {"polls": 0, "items": 0, "applied": 0, "skipped": 0}
        self._sync_last_poll = "ещё не было"
        self.sync_log_path = os.path.join(os.path.dirname(self.db.path), "sync_log.txt")
        
        ui.install_styles(self)
        self._build_header()
        
        self.role = self.db.get("role", "employee")
        if self.role == "manager":
            self._build_manager_ui()
        else:
            self._build_employee_ui()
            
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._after_queue = self.after(QUEUE_MS, self._queue_loop)
        self._after_poll = self.after(3000, self._poll_loop)
        
        if SYNC_AVAILABLE and not self._has_creds() and self.role == "employee":
            self.after(600, self.open_registration)

    def _creds(self):
        emp_id = self.db.get("employee_id", "") or self.db.get("manager_id", "")
        emp_tok = self.db.get("employee_token", "") or self.db.get("manager_token", "") or self.db.get("secret_key", "")
        return emp_id, emp_tok

    def _has_creds(self):
        emp_id, emp_tok = self._creds()
        return bool(emp_id and emp_tok)

    def _build_header(self):
        head = tk.Frame(self, bg=T["accent"], height=74)
        head.pack(fill="x")
        head.pack_propagate(False)
        left = tk.Frame(head, bg=T["accent"])
        left.pack(side="left", padx=24)
        tk.Label(left, text="ТАБЕЛЬ 2.0", bg=T["accent"], fg="white", font=(FONT, 20, "bold")).pack(anchor="w", pady=(16, 0))
        role_text = "Руководитель" if self.role == "manager" else "Сотрудник"
        tk.Label(left, text=f"Режим: {role_text}", bg=T["accent"], fg="#DCEBF8", font=F_SMALL).pack(anchor="w")

    def _build_manager_ui(self):
        self.manager_root = ManagerRoot(self)
        self.manager_root.pack(fill="both", expand=True, padx=16, pady=12)

    def _build_employee_ui(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(12, 16))
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
        self.load_date(self.current)

    # --- Методы синхронизации (сокращены для краткости, логика сохранена) ---
    def _poll_loop(self):
        self._after_poll = None
        try:
            if self.sync_client and self._has_creds():
                self.sync_client.send_async("poll_commands", callback=lambda r: self.sync_queue.put(("poll", r)))
        except Exception as ex:
            self.sync_queue.put(("poll", {"ok": False, "error": str(ex)}))
        self._after_poll = self.after(POLL_MS, self._poll_loop)

    def _queue_loop(self):
        try:
            while True:
                event = self.sync_queue.get_nowait()
                kind, rest = event[0], event[1:]
                if kind == "poll": self._handle_poll(rest[0])
                elif kind == "create": self._on_create_result(rest[0], rest[1] if len(rest) > 1 else "")
                elif kind == "create_manager": self._on_create_manager_result(rest[0], rest[1] if len(rest) > 1 else "")
                elif kind == "create_emp": self._on_create_emp_result(rest[0], rest[1] if len(rest) > 1 else "")
        except queue.Empty: pass
        self._after_queue = self.after(QUEUE_MS, self._queue_loop)

    def _handle_poll(self, result):
        self.sync_stats["polls"] += 1
        self._sync_last_poll = dt.datetime.now().strftime("%H:%M:%S")
        if not result.get("ok"): return
        items = result.get("items", []) or []
        self.sync_stats["items"] += len(items)
        changed = False
        for item in items:
            cmd = item.get("command")
            payload = item.get("payload") or {}
            if cmd == "day_updated":
                if self._apply_day_updated(payload):
                    changed = True
                    self.sync_stats["applied"] += 1
            elif cmd in ("payment_date_entered", "payment_received"):
                if self._apply_payment(payload):
                    changed = True
                    self.sync_stats["applied"] += 1
        if changed:
            self.load_date(self.current)
            if hasattr(self, 'refresh_week'): self.refresh_week()
            if hasattr(self, 'refresh_history'): self.refresh_history()
            ui.toast(self, "Получены обновления")

    def _apply_day_updated(self, payload):
        date = str(payload.get("date") or "").strip()
        entry = payload.get("entry") or {}
        try: version = int(payload.get("version") or 1)
        except: return False
        if not date or not isinstance(entry, dict) or not entry: return False
        local = self.db.load_day(date)
        local_version = 0 if local.is_empty else int(local.version or 1)
        if version <= local_version: return False
        data = dict(entry)
        data.pop("id", None)
        data["date"] = date
        data["version"] = version
        data["sync_status"] = "synced"
        data["approved_at"] = ""
        data.setdefault("rate", self.db.get_float("rate", 250))
        data.setdefault("extra_rate", self.db.get_float("extra_rate", 250))
        self.db.save_day(DayEntry(**data))
        return True

    def _apply_payment(self, payload):
        week = str(payload.get("week_id") or "").strip()
        pay_date = str(payload.get("payment_date") or "").strip()
        if not week: return False
        try: monday = dt.date.fromisoformat(week)
        except: return False
        if self.db.week_received(monday): return False
        if not pay_date: pay_date = self.db.received_on(monday) or dt.date.today().isoformat()
        self.db.set_received(monday, pay_date)
        return True

    def _on_create_result(self, result, name):
        if result.get("ok") and result.get("employee_id"):
            self.db.set("employee_id", str(result.get("employee_id")))
            self.db.set("employee_token", str(result.get("employee_token")))
            self.db.set("secret_key", str(result.get("employee_token")))
            if name and not self.db.get("employee", ""): self.db.set("employee", name)
            if self.sync_client: self.sync_client.set_credentials(self.db.get("employee_id"), self.db.get("employee_token"))
            if self._reg_dialog: self._reg_dialog.destroy()
            TokenDialog(self, self.db.get("employee_token"))
        else:
            if self._reg_dialog: self._reg_dialog.show_error("Ошибка: " + str(result.get("error")))

    def _on_create_manager_result(self, result, name):
        if result.get("ok") and result.get("manager_id"):
            self.db.set("manager_id", str(result.get("manager_id")))
            self.db.set("manager_token", str(result.get("manager_token")))
            if name: self.db.set("employee", name)
            if self._reg_dialog: self._reg_dialog.destroy()
            ui.toast(self, "Руководитель зарегистрирован")
            self._build_manager_ui() # Перестроить UI
        else:
            if self._reg_dialog: self._reg_dialog.show_error("Ошибка: " + str(result.get("error")))

    def _on_create_emp_result(self, result, name):
        if result.get("ok"):
            ui.toast(self, f"Сотрудник {name} создан")
            if hasattr(self, 'manager_root'): self.manager_root.refresh_list()
        else:
            ui.toast(self, "Ошибка создания: " + str(result.get("error")), "err")

    def open_registration(self):
        if not (SYNC_AVAILABLE and self.sync_client): return
        if self._reg_dialog is not None:
            try: self._reg_dialog.lift(); return
            except: self._reg_dialog = None
        RegDialog(self)

    # --- Вкладки сотрудника ---
    def _build_day_tab(self):
        root = self.tab_day
        root.columnconfigure(0, weight=3, uniform="c")
        root.columnconfigure(1, weight=2, uniform="c")
        root.rowconfigure(1, weight=1)
        bar = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"], highlightthickness=1)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(8, 12))
        ttk.Button(bar, text="◀", style="Nav.TButton", command=lambda: self.shift_day(-1)).pack(side="left", padx=(12, 8), pady=10)
        self.lbl_wd = tk.Label(bar, bg=T["surface"], fg=T["accent_dark"], font=(FONT, 16, "bold"))
        self.lbl_wd.pack(side="left", padx=(4, 12))
        self.lbl_date = tk.Label(bar, bg=T["surface"], fg=T["text"], font=(FONT, 14))
        self.lbl_date.pack(side="left")
        ttk.Button(bar, text="▶", style="Nav.TButton", command=lambda: self.shift_day(1)).pack(side="left", padx=10)
        ttk.Button(bar, text="Сегодня", style="Ghost.TButton", command=lambda: self.load_date(dt.date.today())).pack(side="left", padx=6)
        
        left = tk.Frame(root, bg=T["bg"])
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        
        c_time = Card(left, "Время работы")
        c_time.grid(row=0, column=0, sticky="ew")
        b = c_time.body
        row = tk.Frame(b, bg=T["surface"])
        row.pack(fill="x")
        self.f_start = Field(row, "Начало", width=8, hint="8:00")
        self.f_start.pack(side="left", padx=(0, 16))
        self.f_end = Field(row, "Конец", width=8, hint="17:00")
        self.f_end.pack(side="left")
        self.f_start.var.trace_add("write", lambda *a: self.recalc())
        self.f_end.var.trace_add("write", lambda *a: self.recalc())
        
        c_work = Card(left, "Объём и качество произведённых работ")
        c_work.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.txt_works = tk.Text(c_work.body, height=6, font=(FONT, 12), wrap="word", bg=T["white"], fg=T["text"], relief="flat", highlightthickness=1, highlightbackground=T["border"], padx=10, pady=8)
        self.txt_works.pack(fill="both", expand=True)
        
        right = tk.Frame(root, bg=T["bg"])
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        
        c_calc = Card(right, "Расчёт за день")
        c_calc.grid(row=0, column=0, sticky="ew")
        bc = c_calc.body
        self.lbl_total_day = tk.Label(bc, text="0 ₽", bg=T["surface"], fg=T["ok"], font=(FONT, 22, "bold"))
        self.lbl_total_day.pack(side="right", pady=10)
        tk.Label(bc, text="ИТОГО ЗА ДЕНЬ", bg=T["surface"], fg=T["accent_dark"], font=F_BODY_B).pack(side="left", pady=10)
        
        c_act = Card(right)
        c_act.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        pad = tk.Frame(c_act, bg=T["surface"])
        pad.pack(fill="x", padx=16, pady=14)
        self.btn_save = ttk.Button(pad, text="СОХРАНИТЬ ДЕНЬ", style="Accent.TButton", command=self.save_day)
        self.btn_save.pack(fill="x")
        # Кнопка "Одобрить день" УБРАНА для сотрудника (ТЗ п. 0-2)

    def _build_week_tab(self):
        root = self.tab_week
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        bar = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"], highlightthickness=1)
        bar.grid(row=0, column=0, sticky="ew", pady=(8, 12))
        ttk.Button(bar, text="◀", style="Nav.TButton", command=lambda: self.shift_week(-1)).pack(side="left", padx=(12, 8), pady=10)
        self.lbl_week = tk.Label(bar, bg=T["surface"], fg=T["accent_dark"], font=(FONT, 16, "bold"))
        self.lbl_week.pack(side="left", padx=10)
        ttk.Button(bar, text="▶", style="Nav.TButton", command=lambda: self.shift_week(1)).pack(side="left", padx=8)
        
        cols = ("wd", "date", "time", "hours", "xtime", "xhours", "works", "pay", "xpay", "bonus", "pen", "total", "appr")
        titles = ("День", "Дата", "Время", "Часы", "Доп. время", "Доп. часы", "Основные работы", "Доп. работы", "Премия", "Штраф", "Итого", "Одобрено")
        widths = (50, 70, 110, 90, 100, 80, 260, 100, 90, 80, 100, 100, 80)
        
        wrap = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"], highlightthickness=1)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for i, (c, t, w) in enumerate(zip(cols, titles, widths)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c not in ("works", "appr") else "center", stretch=(c == "works"))
            # Применяем цветные стили заголовков (хак через конфигурацию, если поддерживается, или оставляем стандартный, но данные цветные)
            if c == "works": self.tree.heading(c, text=t) # H_Main
            elif c == "xpay": self.tree.heading(c, text=t) # H_Extra
            elif c == "bonus": self.tree.heading(c, text=t) # H_Bonus
            elif c == "pen": self.tree.heading(c, text=t) # H_Penalty
            elif c == "appr": self.tree.heading(c, text=t) # H_Appr

        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.tag_configure("today", background=T["accent_light"], font=F_BODY_B)
        self.tree.tag_configure("total", background="#D6E6F4", foreground=APPROVED_COLOR, font=(FONT, 16, "bold")) # ТЗ: Итого зеленым и жирным
        
        # Блок получения зарплаты для сотрудника (ТЗ п. 0-2)
        pay_frame = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"], highlightthickness=1)
        pay_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        tk.Label(pay_frame, text="Дата получения зарплаты:", bg=T["surface"], fg=T["text"], font=F_BODY_B).pack(side="left", padx=16, pady=12)
        self.f_pay_date = Field(pay_frame, "", width=12, hint="ДД.ММ.ГГГГ")
        self.f_pay_date.pack(side="left", padx=(0, 12))
        ttk.Button(pay_frame, text="Получил", style="Accent.TButton", command=self.mark_received).pack(side="left", pady=10)

    def _build_hist_tab(self):
        root = self.tab_hist
        root.rowconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        side = Card(root, "Месяцы")
        side.grid(row=0, column=0, sticky="nsw", pady=8, padx=(0, 12))
        self.lst_months = tk.Listbox(side.body, width=24, font=F_BODY, bd=0, bg=T["white"], fg=T["text"], relief="flat", highlightthickness=1, highlightbackground=T["border"], selectbackground=T["accent"], selectforeground="white")
        self.lst_months.pack(fill="both", expand=True, ipady=6)
        self.lst_months.bind("<<ListboxSelect>>", self._hist_pick)
        main = Card(root, "Записи месяца")
        main.grid(row=0, column=1, sticky="nsew", pady=8)
        cols = ("date", "wd", "time", "hours", "xhours", "works", "total")
        titles = ("Дата", "День", "Время", "Часы", "Доп.", "Работы", "Итого, ₽")
        widths = (90, 50, 110, 80, 70, 400, 110)
        self.htree = ttk.Treeview(main.body, columns=cols, show="headings")
        for c, t, w in zip(cols, titles, widths):
            self.htree.heading(c, text=t)
            self.htree.column(c, width=w, anchor="center" if c != "works" else "w", stretch=(c == "works"))
        vs = tk.Scrollbar(main.body, orient="vertical", command=self.htree.yview)
        self.htree.configure(yscrollcommand=vs.set)
        self.htree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

    def _build_settings_tab(self):
        root = self.tab_set
        root.columnconfigure(0, weight=1)
        c1 = Card(root, "Данные для отчётов")
        c1.grid(row=0, column=0, sticky="new", pady=8)
        self.s_emp = Field(c1.body, "Ф. И. О. работника", width=32, justify="left")
        self.s_emp.pack(fill="x", pady=6)
        ttk.Button(c1.body, text="СОХРАНИТЬ", style="Accent.TButton", command=lambda: [self.db.set("employee", self.s_emp.get()), ui.toast(self, "Сохранено")]).pack(fill="x", pady=(14, 0))
        c2 = Card(root, "Синхронизация")
        c2.grid(row=1, column=0, sticky="new", pady=8)
        ttk.Button(c2.body, text="Регистрация (новый аккаунт)", style="Accent.TButton", command=self.open_registration).pack(fill="x", pady=4)

    def load_date(self, d):
        self._loading = True
        self.current = d
        e = self.db.load_day(d)
        self.lbl_wd.config(text=WEEKDAYS_RU[d.weekday()])
        self.lbl_date.config(text="%02d.%02d.%d" % (d.day, d.month, d.year))
        self.f_start.set(fmt_time(e.start) if e.start is not None else "")
        self.f_end.set(fmt_time(e.end) if e.end is not None else "")
        self.txt_works.delete("1.0", "end")
        self.txt_works.insert("1.0", e.works)
        self._loading = False
        self.recalc()
        self.refresh_week()

    def recalc(self, *_):
        if self._loading: return
        e = DayEntry(date=self.current.isoformat())
        e.start = parse_time(self.f_start.get())
        e.end = parse_time(self.f_end.get())
        e.works = self.txt_works.get("1.0", "end").strip()
        e.rate = self.db.get_float("rate", 250)
        self.lbl_total_day.config(text=fmt_money(e.total_pay))

    def save_day(self):
        e = DayEntry(date=self.current.isoformat())
        e.start = parse_time(self.f_start.get())
        e.end = parse_time(self.f_end.get())
        e.works = self.txt_works.get("1.0", "end").strip()
        e.rate = self.db.get_float("rate", 250)
        self.db.save_day(e)
        ui.toast(self, "Сохранено")
        self.refresh_week()

    def shift_day(self, n): self.load_date(self.current + dt.timedelta(days=n))
    def shift_week(self, n): self.load_date(self.current + dt.timedelta(weeks=n))

    def mark_received(self):
        pay_date = _parse_date_ru(self.f_pay_date.get())
        if not pay_date:
            ui.toast(self, "Введите дату в формате ДД.ММ.ГГГГ", "warn")
            return
        monday = week_start(self.current)
        self.db.set_received(monday, pay_date.isoformat())
        version = self.db.increment_week_version(monday)
        emp_id, emp_tok = self._creds()
        if SYNC_AVAILABLE and self.sync_client and emp_id and emp_tok:
            self.sync_client.send_async("payment_received", emp_id, emp_tok, monday.isoformat(), {"week_id": monday.isoformat(), "payment_date": pay_date.isoformat(), "payment_confirmed": True}, version)
        ui.toast(self, "Зарплата получена ✓")
        self.refresh_week()

    def refresh_week(self):
        days = self.db.week_days(self.current)
        self.lbl_week.config(text=week_title(self.current))
        self.tree.delete(*self.tree.get_children())
        today = dt.date.today()
        for i, e in enumerate(days):
            d = e.date_obj
            tags = ["today"] if d == today else (["odd"] if i % 2 else [])
            time_s = ("%s — %s" % (fmt_time(e.start), fmt_time(e.end)) if e.start is not None and e.end is not None else "—")
            xt = ("%s — %s" % (fmt_time(e.extra_start), fmt_time(e.extra_end)) if e.extra_on and e.extra_start is not None else "—")
            
            # ТЗ: Галочки зеленые и жирные в 3 раза (кегль 24 bold)
            appr_text = "✓" if e.approved_at else ("■" if not e.is_empty else "")
            appr_tag = "appr_yes" if e.approved_at else "appr_no"
            
            self.tree.insert("", "end", iid="d:" + e.date, tags=tags, values=(
                ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                "%02d.%02d" % (d.day, d.month), time_s, fmt_hm_short(e.work_min) if e.work_min else "—",
                xt, fmt_hm_short(e.extra_min) if e.extra_min else "—",
                (e.works.replace("\n", " ")[:120] or "—"),
                fmt_money(e.day_pay) if e.day_pay else "—", fmt_money(e.extra_pay) if e.extra_pay else "—",
                fmt_money(e.bonus) if e.bonus else "—", fmt_money(e.penalty) if e.penalty else "—",
                fmt_money(e.total_pay) if e.total_pay else "—", appr_text
            ))
        # Настройка цветов для галочек через теги Treeview
        self.tree.tag_configure("appr_yes", foreground=APPROVED_COLOR, font=(FONT, 24, "bold"))
        self.tree.tag_configure("appr_no", foreground="#999999", font=(FONT, 14))

        t = Totals(days)
        # ТЗ: строка "Итого" зеленая и жирная
        self.tree.insert("", "end", iid="total", tags=("total",), values=(
            "", "ИТОГО", "", fmt_hm_short(t.work_min), "", fmt_hm_short(t.extra_min),
            "Дней: %d" % t.worked_days, fmt_money(t.day_pay), fmt_money(t.extra_pay),
            fmt_money(t.bonus), fmt_money(t.penalty), fmt_money(t.total_pay), ""
        ))

    def refresh_history(self):
        months = self.db.filled_months()
        cur = self.current.strftime("%Y-%m")
        if cur not in months: months = [cur] + months
        self.lst_months.delete(0, "end")
        self._months = months
        for m in months:
            y, mm = m.split("-")
            self.lst_months.insert("end", "  %s %s" % (MONTHS_RU[int(mm) - 1], y))
        self._fill_history(self.current)

    def _hist_pick(self, _e):
        sel = self.lst_months.curselection()
        if not sel: return
        y, m = self._months[sel[0]].split("-")
        self._fill_history(dt.date(int(y), int(m), 1))

    def _fill_history(self, anchor):
        self.htree.delete(*self.htree.get_children())
        days = self.db.month_days(anchor)
        for e in days:
            if not e.is_empty:
                d = e.date_obj
                self.htree.insert("", "end", iid="d:" + e.date, values=(
                    "%02d.%02d.%d" % (d.day, d.month, d.year),
                    ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                    "%s — %s" % (fmt_time(e.start), fmt_time(e.end)) if e.start is not None else "—",
                    fmt_hm_short(e.work_min), fmt_hm_short(e.extra_min) if e.extra_min else "—",
                    e.works.replace("\n", " ")[:150], fmt_money(e.total_pay)
                ))

    def _on_tab(self, _e):
        try:
            tab = self.nb.index(self.nb.select())
        except: return
        if tab == 1: self.refresh_week()
        elif tab == 2: self.refresh_history()

    def _on_close(self):
        for aid in (self._after_poll, self._after_queue):
            if aid:
                try: self.after_cancel(aid)
                except: pass
        self.db.close()
        self.destroy()


# ================= ИНТЕРФЕЙС РУКОВОДИТЕЛЯ =================

class ManagerRoot(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=T["bg"])
        self.app = app
        self.pack(fill="both", expand=True)
        
        top = tk.Frame(self, bg=T["bg"])
        top.pack(fill="x", pady=(0, 16))
        tk.Label(top, text="Список сотрудников", bg=T["bg"], fg=T["accent_dark"], font=ui.F_H1).pack(side="left")
        ttk.Button(top, text="+ Добавить сотрудника", style="Accent.TButton", command=self.open_add_emp).pack(side="right")
        ttk.Button(top, text="Регистрация (новый аккаунт)", style="Ghost.TButton", command=self.app.open_registration).pack(side="right", padx=(0, 12))
        
        self.list_frame = tk.Frame(self, bg=T["bg"])
        self.list_frame.pack(fill="both", expand=True)
        
        self.refresh_list()

    def refresh_list(self):
        for w in self.list_frame.winfo_children(): w.destroy()
        mgr_id = self.app.db.get("manager_id", "")
        mgr_tok = self.app.db.get("manager_token", "")
        if not (mgr_id and mgr_tok):
            tk.Label(self.list_frame, text="Нет данных руководителя", bg=T["bg"], fg=T["danger"], font=F_BODY).pack(pady=20)
            return
            
        self.app.sync_client.send_async("list_employees", mgr_id, mgr_tok, callback=self._on_list)

    def _on_list(self, result):
        if not result.get("ok"):
            tk.Label(self.list_frame, text="Ошибка загрузки: " + str(result.get("error")), bg=T["bg"], fg=T["danger"], font=F_BODY).pack(pady=20)
            return
            
        employees = result.get("employees", [])
        if not employees:
            tk.Label(self.list_frame, text="Список сотрудников пуст", bg=T["bg"], fg=T["text_muted"], font=F_BODY).pack(pady=20)
            return
            
        for emp in employees:
            btn = tk.Button(self.list_frame, text=emp["name"].upper(), bg=T["surface"], fg=T["accent_dark"], 
                            font=F_GIANT, relief="flat", bd=0, cursor="hand2", anchor="w", padx=24, pady=20,
                            command=lambda e=emp: self.app.show_employee_view(e))
            btn.pack(fill="x", pady=6)
            btn.bind("<Enter>", lambda e: e.widget.config(bg=T["accent_light"]))
            btn.bind("<Leave>", lambda e: e.widget.config(bg=T["surface"]))

    def open_add_emp(self):
        CreateEmployeeDialog(self.app)


class EmployeeView(tk.Frame):
    def __init__(self, app, employee):
        super().__init__(app, bg=T["bg"])
        self.app = app
        self.emp = employee
        self.current = dt.date.today()
        self.pack(fill="both", expand=True)
        
        top = tk.Frame(self, bg=T["bg"])
        top.pack(fill="x", pady=(0, 16))
        ttk.Button(top, text="← Назад к списку", style="Ghost.TButton", command=self.app._build_manager_ui).pack(side="left")
        tk.Label(top, text=f"Сотрудник: {employee['name']}", bg=T["bg"], fg=T["accent_dark"], font=ui.F_H1).pack(side="left", padx=20)
        
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.tab_week = tk.Frame(self.nb, bg=T["bg"])
        self.tab_hist = tk.Frame(self.nb, bg=T["bg"])
        self.nb.add(self.tab_week, text="Неделя")
        self.nb.add(self.tab_hist, text="История")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)
        
        self._build_week_tab()
        self._build_hist_tab()
        self.refresh_week()

    def _build_week_tab(self):
        root = self.tab_week
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        bar = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"], highlightthickness=1)
        bar.grid(row=0, column=0, sticky="ew", pady=(8, 12))
        ttk.Button(bar, text="◀", style="Nav.TButton", command=lambda: self.shift_week(-1)).pack(side="left", padx=(12, 8), pady=10)
        self.lbl_week = tk.Label(bar, bg=T["surface"], fg=T["accent_dark"], font=(FONT, 16, "bold"))
        self.lbl_week.pack(side="left", padx=10)
        ttk.Button(bar, text="▶", style="Nav.TButton", command=lambda: self.shift_week(1)).pack(side="left", padx=8)
        
        cols = ("wd", "date", "time", "hours", "xtime", "xhours", "works", "pay", "xpay", "bonus", "pen", "total", "appr")
        titles = ("День", "Дата", "Время", "Часы", "Доп. время", "Доп. часы", "Основные работы", "Доп. работы", "Премия", "Штраф", "Итого", "Одобрено")
        widths = (50, 70, 110, 90, 100, 80, 260, 100, 90, 80, 100, 100, 90)
        
        wrap = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"], highlightthickness=1)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for c, t, w in zip(cols, titles, widths):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c not in ("works", "appr") else "center", stretch=(c == "works"))
            
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.tag_configure("total", background="#D6E6F4", foreground=APPROVED_COLOR, font=(FONT, 16, "bold"))
        
        # Привязка клика по колонке "Одобрено"
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

    def _build_hist_tab(self):
        root = self.tab_hist
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        main = Card(root, "История записей")
        main.grid(row=0, column=0, sticky="nsew", pady=8)
        cols = ("date", "wd", "time", "hours", "works", "total")
        titles = ("Дата", "День", "Время", "Часы", "Работы", "Итого, ₽")
        widths = (90, 50, 110, 80, 400, 110)
        self.htree = ttk.Treeview(main.body, columns=cols, show="headings")
        for c, t, w in zip(cols, titles, widths):
            self.htree.heading(c, text=t)
            self.htree.column(c, width=w, anchor="center" if c != "works" else "w", stretch=(c == "works"))
        vs = tk.Scrollbar(main.body, orient="vertical", command=self.htree.yview)
        self.htree.configure(yscrollcommand=vs.set)
        self.htree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.refresh_hist()

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        column = self.tree.identify_column(event.x)
        col_idx = int(column.replace("#", "")) - 1
        cols = ("wd", "date", "time", "hours", "xtime", "xhours", "works", "pay", "xpay", "bonus", "pen", "total", "appr")
        if cols[col_idx] != "appr": return
        
        item = self.tree.identify_row(event.y)
        if not item or item == "total" or not item.startswith("d:"): return
        
        date_str = item[2:]
        d = dt.date.fromisoformat(date_str)
        entry = self.app.db.load_day(date_str)
        if entry.is_empty: return
        
        if entry.approved_at:
            ui.toast(self.app, "День уже одобрен", "warn")
            return
            
        # Одобрение дня сотрудника
        mgr_id = self.app.db.get("manager_id", "")
        mgr_tok = self.app.db.get("manager_token", "")
        version = self.app.db.get_day_version(date_str)
        
        self.app.sync_client.send_async("approve_employee_day", mgr_id, mgr_tok, self.emp["employee_id"], date_str, version, callback=lambda r: self._on_approve_result(r, date_str))

    def _on_approve_result(self, result, date_str):
        if result.get("ok"):
            self.app.db.mark_approved(date_str)
            ui.toast(self.app, "День одобрен ✓")
            self.refresh_week()
        else:
            ui.toast(self.app, "Ошибка одобрения: " + str(result.get("error")), "err")

    def refresh_week(self):
        days = self.app.db.week_days(self.current, employee_id=self.emp["employee_id"])
        self.lbl_week.config(text=week_title(self.current))
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(days):
            d = e.date_obj
            tags = ["odd"] if i % 2 else []
            time_s = ("%s — %s" % (fmt_time(e.start), fmt_time(e.end)) if e.start is not None and e.end is not None else "—")
            xt = ("%s — %s" % (fmt_time(e.extra_start), fmt_time(e.extra_end)) if e.extra_on and e.extra_start is not None else "—")
            
            appr_text = "✓" if e.approved_at else ("■" if not e.is_empty else "")
            appr_tag = "appr_yes" if e.approved_at else "appr_no"
            
            self.tree.insert("", "end", iid="d:" + e.date, tags=(tags + [appr_tag]), values=(
                ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                "%02d.%02d" % (d.day, d.month), time_s, fmt_hm_short(e.work_min) if e.work_min else "—",
                xt, fmt_hm_short(e.extra_min) if e.extra_min else "—",
                (e.works.replace("\n", " ")[:120] or "—"),
                fmt_money(e.day_pay) if e.day_pay else "—", fmt_money(e.extra_pay) if e.extra_pay else "—",
                fmt_money(e.bonus) if e.bonus else "—", fmt_money(e.penalty) if e.penalty else "—",
                fmt_money(e.total_pay) if e.total_pay else "—", appr_text
            ))
        self.tree.tag_configure("appr_yes", foreground=APPROVED_COLOR, font=(FONT, 24, "bold"))
        self.tree.tag_configure("appr_no", foreground="#999999", font=(FONT, 14))

        t = Totals(days)
        self.tree.insert("", "end", iid="total", tags=("total",), values=(
            "", "ИТОГО", "", fmt_hm_short(t.work_min), "", fmt_hm_short(t.extra_min),
            "Дней: %d" % t.worked_days, fmt_money(t.day_pay), fmt_money(t.extra_pay),
            fmt_money(t.bonus), fmt_money(t.penalty), fmt_money(t.total_pay), ""
        ))

    def refresh_hist(self):
        self.htree.delete(*self.htree.get_children())
        days = self.app.db.month_days(self.current, employee_id=self.emp["employee_id"])
        for e in days:
            if not e.is_empty:
                d = e.date_obj
                self.htree.insert("", "end", values=(
                    "%02d.%02d.%d" % (d.day, d.month, d.year),
                    ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()],
                    "%s — %s" % (fmt_time(e.start), fmt_time(e.end)) if e.start is not None else "—",
                    fmt_hm_short(e.work_min), e.works.replace("\n", " ")[:150], fmt_money(e.total_pay)
                ))

    def shift_week(self, n): 
        self.current = self.current + dt.timedelta(weeks=n)
        self.refresh_week()
        self.refresh_hist()

    def _on_tab(self, _e):
        try:
            tab = self.nb.index(self.nb.select())
        except: return
        if tab == 0: self.refresh_week()
        elif tab == 1: self.refresh_hist()


if __name__ == "__main__":
    App().mainloop()
