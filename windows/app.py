# -*- coding: utf-8 -*-
"""
Табель — учёт рабочего времени и выплат.
Windows-версия (Tkinter). Собирается в .exe через PyInstaller.
ВЕРСИЯ 2.0.0 — синхронизация с сервером (Google Apps Script), одобрения дней.
"""
import os
import sys
import queue
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

# === СИНХРОНИЗАЦИЯ С СЕРВЕРОМ ===
try:
    from sync_client import SyncClient
    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False

SYNC_API_URL = ("https://script.google.com/macros/s/"
                "AKfycbwDWAS8t__5y3WdFudGQa8OMyWxxBYl56tiJY5RHjR1EmBPiyTrlXUpa2CcmI-q3sQBdQ/exec")
SYNC_API_TOKEN = "28096b2395454f05a7ce7a2b0fcfe3b2e58fd9bed8d5465db4560056a662659c"

APPROVED_COLOR = "#249d07"
POLL_MS = 30000          # период опроса очереди сервера
QUEUE_MS = 100           # период разбора очереди событий UI


def _asset(name):
    """Путь к ассету: в onefile-сборке — из sys._MEIPASS, иначе — из папки assets."""
    bases = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            bases.append(os.path.join(meipass, "assets"))
        bases.append(os.path.join(os.path.dirname(sys.executable), "assets"))
    bases.append(os.path.join(HERE, "assets"))
    for b in bases:
        p = os.path.join(b, name)
        if os.path.exists(p):
            return p
    return os.path.join(bases[0], name)


def _ensure_pdf_fonts():
    """Регистрирует DejaVu для reportlab из ассетов (в т.ч. из _MEIPASS).
    reports._register_font() увидит имя 'Tab' и переиспользует его."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return
    try:
        reg = pdfmetrics.getRegisteredFontNames()
        if "Tab" in reg:
            return
        regular = _asset("DejaVuSans.ttf")
        bold = _asset("DejaVuSans-Bold.ttf")
        if os.path.exists(regular):
            pdfmetrics.registerFont(TTFont("Tab", regular))
        if os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("TabB", bold))
    except Exception:
        pass


def _parse_date_ru(text):
    """'05.10.2026' / '05/10/2026' / '05-10-2026' / '5.10.2026' / '05.10.26' -> date.
    None, если ввод не распознан или дата не существует."""
    s = str(text or "").strip()
    s = s.replace("/", ".").replace("-", ".").replace(" ", "")
    if not s:
        return None
    parts = s.split(".")
    if len(parts) != 3:
        return None
    if not all(p.isascii() and p.isdigit() for p in parts):
        return None
    d_s, m_s, y_s = parts
    if len(y_s) == 2:
        y_s = ("20" if int(y_s) < 70 else "19") + y_s
    if not (len(d_s) in (1, 2) and len(m_s) in (1, 2) and len(y_s) == 4):
        return None
    try:
        return dt.date(int(y_s), int(m_s), int(d_s))
    except ValueError:
        return None


def _fmt_date_ru(iso):
    try:
        d = dt.date.fromisoformat(str(iso))
        return "%02d.%02d.%d" % (d.day, d.month, d.year)
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------- диалоги синхр.
class RegDialog(tk.Toplevel):
    """Первичная регистрация сотрудника: ФИО + дата рождения -> create_account."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        app._reg_dialog = self
        self.title("Первичная регистрация")
        self.resizable(False, False)
        self.transient(app)
        self.configure(bg=T["surface"])
        pad = tk.Frame(self, bg=T["surface"])
        pad.pack(fill="both", padx=18, pady=16)
        tk.Label(pad, text="Регистрация сотрудника", bg=T["surface"],
                 fg=T["accent_dark"], font=ui.F_H2).pack(anchor="w")
        tk.Label(pad, text="ФИО и дата рождения нужны серверу для поиска аккаунта "
                           "при привязке телефона и восстановлении истории.",
                 bg=T["surface"], fg=T["text_muted"], font=F_SMALL,
                 wraplength=400, justify="left").pack(anchor="w", pady=(4, 10))
        self.f_name = Field(pad, "Ф. И. О. работника", width=34, justify="left")
        self.f_name.pack(fill="x")
        self.f_birth = Field(pad, "Дата рождения", width=12, hint="ДД.ММ.ГГГГ")
        self.f_birth.pack(fill="x", pady=(8, 0))
        self.lbl_err = tk.Label(pad, text="", bg=T["surface"], fg=T["danger"],
                                font=F_SMALL, wraplength=400, justify="left")
        self.lbl_err.pack(anchor="w", pady=(8, 0))
        row = tk.Frame(pad, bg=T["surface"])
        row.pack(fill="x", pady=(10, 0))
        self.btn_ok = ttk.Button(row, text="Зарегистрировать", style="Accent.TButton",
                                 command=self.submit)
        self.btn_ok.pack(side="left")
        ttk.Button(row, text="Позже", style="Ghost.TButton",
                   command=self.destroy).pack(side="left", padx=(8, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def submit(self):
        name = self.f_name.get().strip()
        birth = _parse_date_ru(self.f_birth.get())
        if not name:
            self.show_error("Укажите Ф. И. О. работника.")
            return
        if birth is None:
            self.show_error("Дата рождения — в формате ДД.ММ.ГГГГ.")
            return
        self.btn_ok.config(state="disabled")
        self.lbl_err.config(text="Отправка на сервер…", fg=T["text_muted"])
        self.app.sync_client.send_async(
            "create_account", name, birth.isoformat(),
            callback=lambda r, n=name: self.app.sync_queue.put(("create", r, n)))

    def show_error(self, text):
        self.lbl_err.config(text=text, fg=T["danger"])
        self.btn_ok.config(state="normal")

    def destroy(self):
        if getattr(self.app, "_reg_dialog", None) is self:
            self.app._reg_dialog = None
        super().destroy()


class TokenDialog(tk.Toplevel):
    """Показ employee_token с кнопкой копирования (для ввода на телефоне)."""

    def __init__(self, app, token):
        super().__init__(app)
        self.app = app
        self.token = token
        self.title("Токен сотрудника")
        self.resizable(False, False)
        self.transient(app)
        self.configure(bg=T["surface"])
        pad = tk.Frame(self, bg=T["surface"])
        pad.pack(fill="both", padx=18, pady=16)
        tk.Label(pad, text="Аккаунт создан. Токен сотрудника:", bg=T["surface"],
                 fg=T["accent_dark"], font=ui.F_H2).pack(anchor="w")
        tk.Label(pad, text="Введите этот код на телефоне: «Настройки → "
                           "Синхронизация с Windows → Привязать».",
                 bg=T["surface"], fg=T["text_muted"], font=F_SMALL,
                 wraplength=420, justify="left").pack(anchor="w", pady=(4, 10))
        self.ent = tk.Entry(pad, font=("Consolas", 13), justify="center",
                            bg=T["white"], fg=T["text"], relief="flat",
                            highlightthickness=1, highlightbackground=T["border"],
                            insertbackground=T["text"], state="readonly",
                            readonlybackground=T["white"])
        self.ent.pack(fill="x", ipady=7)
        self.ent.config(state="normal")
        self.ent.insert(0, token)
        self.ent.config(state="readonly")
        row = tk.Frame(pad, bg=T["surface"])
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="Скопировать", style="Accent.TButton",
                   command=self.copy).pack(side="left")
        ttk.Button(row, text="Закрыть", style="Ghost.TButton",
                   command=self.destroy).pack(side="left", padx=(8, 0))

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.token)
        ui.toast(self.app, "Токен скопирован в буфер обмена")


class RestoreDialog(tk.Toplevel):
    """Восстановление аккаунта на этом ПК: restore_account(device_type='windows')."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        app._restore_dialog = self
        self.title("Восстановление аккаунта")
        self.resizable(False, False)
        self.transient(app)
        self.configure(bg=T["surface"])
        pad = tk.Frame(self, bg=T["surface"])
        pad.pack(fill="both", padx=18, pady=16)
        tk.Label(pad, text="Перенос аккаунта на этот компьютер", bg=T["surface"],
                 fg=T["accent_dark"], font=ui.F_H2).pack(anchor="w")
        tk.Label(pad, text="Укажите те же ФИО и дату рождения, что при регистрации. "
                           "История дней и закрытые недели будут загружены с сервера. "
                           "Внимание: старый компьютер будет отвязан от аккаунта.",
                 bg=T["surface"], fg=T["text_muted"], font=F_SMALL,
                 wraplength=420, justify="left").pack(anchor="w", pady=(4, 10))
        self.f_name = Field(pad, "Ф. И. О. работника", width=34, justify="left")
        self.f_name.set(app.db.get("employee", ""))
        self.f_name.pack(fill="x")
        self.f_birth = Field(pad, "Дата рождения", width=12, hint="ДД.ММ.ГГГГ")
        self.f_birth.pack(fill="x", pady=(8, 0))
        self.lbl_err = tk.Label(pad, text="", bg=T["surface"], fg=T["danger"],
                                font=F_SMALL, wraplength=420, justify="left")
        self.lbl_err.pack(anchor="w", pady=(8, 0))
        row = tk.Frame(pad, bg=T["surface"])
        row.pack(fill="x", pady=(10, 0))
        self.btn_ok = ttk.Button(row, text="Восстановить", style="Accent.TButton",
                                 command=self.submit)
        self.btn_ok.pack(side="left")
        ttk.Button(row, text="Отмена", style="Ghost.TButton",
                   command=self.destroy).pack(side="left", padx=(8, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def submit(self):
        name = self.f_name.get().strip()
        birth = _parse_date_ru(self.f_birth.get())
        if not name:
            self.show_error("Укажите Ф. И. О. работника.")
            return
        if birth is None:
            self.show_error("Дата рождения — в формате ДД.ММ.ГГГГ.")
            return
        self.btn_ok.config(state="disabled")
        self.lbl_err.config(text="Запрос к серверу…", fg=T["text_muted"])
        self.app.sync_client.send_async(
            "restore_account", name, birth.isoformat(), "windows",
            callback=lambda r: self.app.sync_queue.put(("restore", r)))

    def show_error(self, text):
        self.lbl_err.config(text=text, fg=T["danger"])
        self.btn_ok.config(state="normal")

    def destroy(self):
        if getattr(self.app, "_restore_dialog", None) is self:
            self.app._restore_dialog = None
        super().destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Табель 2.0 — учёт рабочего времени и выплат")
        self.geometry("1180x760")
        self.minsize(1040, 700)
        self.configure(bg=T["bg"])
        try:
            self.iconbitmap(_asset("icon.ico"))
        except Exception:
            pass

        self.db = Storage()
        self.current = dt.date.today()
        self._loading = False
        self._locked = False
        self._reg_dialog = None
        self._restore_dialog = None
        self._sync_last_error = ""
        self._after_poll = None
        self._after_queue = None

        # --- сетевой слой: device_id.txt рядом с БД ---
        self.sync_queue = queue.Queue()
        self.sync_client = None
        if SYNC_AVAILABLE:
            dev_file = os.path.join(os.path.dirname(self.db.path), "device_id.txt")
            self.sync_client = SyncClient(SYNC_API_URL, SYNC_API_TOKEN, dev_file)
            emp_id, emp_tok = self._creds()
            if emp_id and emp_tok:
                self.sync_client.set_credentials(emp_id, emp_tok)

        ui.install_styles(self)
        self._build_header()
        self._build_tabs()
        self.load_date(self.current)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-s>", lambda e: self.save_day())
        self.bind("<Prior>", lambda e: self.shift_day(-1))
        self.bind("<Next>", lambda e: self.shift_day(1))

        # --- таймеры сети: разбор очереди и поллинг ---
        self._after_queue = self.after(QUEUE_MS, self._queue_loop)
        self._after_poll = self.after(3000, self._poll_loop)
        if SYNC_AVAILABLE and not self._has_creds():
            self.after(600, self.open_registration)

    # ------------------------------------------------------------- синхронизация
    def _creds(self):
        emp_id = self.db.get("employee_id", "")
        emp_tok = self.db.get("employee_token", "") or self.db.get("secret_key", "")
        return emp_id, emp_tok

    def _has_creds(self):
        emp_id, emp_tok = self._creds()
        return bool(emp_id and emp_tok)

    def _poll_loop(self):
        """Раз в 30 секунд: опрос очереди сервера в daemon-потоке."""
        self._after_poll = None
        try:
            if self.sync_client and self._has_creds():
                self.sync_client.send_async(
                    "poll_commands",
                    callback=lambda r: self.sync_queue.put(("poll", r)))
        except Exception as ex:
            self.sync_queue.put(("poll", {"ok": False, "error": str(ex)}))
        self._after_poll = self.after(POLL_MS, self._poll_loop)

    def _queue_loop(self):
        """Главный поток разбирает очередь событий от сетевых потоков."""
        try:
            while True:
                event = self.sync_queue.get_nowait()
                kind, rest = event[0], event[1:]
                try:
                    if kind == "poll":
                        self._handle_poll(rest[0])
                    elif kind == "create":
                        self._on_create_result(rest[0], rest[1] if len(rest) > 1 else "")
                    elif kind == "restore":
                        self._on_restore_result(rest[0])
                    elif kind == "approved_sent":
                        self._on_approved_sent(rest[0])
                except Exception as ex:
                    self._sync_last_error = str(ex)
        except queue.Empty:
            pass
        except Exception as ex:
            self._sync_last_error = str(ex)
        self._after_queue = self.after(QUEUE_MS, self._queue_loop)

    def _handle_poll(self, result):
        if not result.get("ok"):
            err = str(result.get("error", ""))
            if err not in ("no_connection", "timeout", "device not registered"):
                self._sync_last_error = err
            return
        self._sync_last_error = ""
        changed = False
        touch_current = False
        for item in result.get("items", []) or []:
            cmd = item.get("command")
            payload = item.get("payload") or {}
            try:
                if cmd == "day_updated":
                    if self._apply_day_updated(payload):
                        changed = True
                        touch_current = touch_current or (
                            payload.get("date") == self.current.isoformat())
                elif cmd in ("payment_date_entered", "payment_received"):
                    if self._apply_payment(payload):
                        changed = True
                        touch_current = True
            except Exception as ex:
                self._sync_last_error = str(ex)
        if changed:
            if touch_current:
                self.load_date(self.current)
            self.refresh_week()
            self.refresh_history()
            ui.toast(self, "Получены обновления с телефона")

    def _apply_day_updated(self, payload):
        """Применяет день с телефона, только если version больше локальной."""
        date = str(payload.get("date") or "").strip()
        entry = payload.get("entry") or {}
        try:
            version = int(payload.get("version") or 1)
        except (TypeError, ValueError):
            return False
        if not date or not isinstance(entry, dict) or not entry:
            return False
        local = self.db.load_day(date)
        local_version = 0 if local.is_empty else int(local.version or 1)
        if version <= local_version:
            return False
        data = dict(entry)
        data.pop("id", None)
        data["date"] = date
        data["version"] = version
        data["sync_status"] = "synced"
        for k in ("lunch_on", "extra_on", "extra_use_fixed", "penalty_on"):
            data.setdefault(k, False)
        data.setdefault("approved_at", local.approved_at or "")
        data.setdefault("rate", self.db.get_float("rate", 250))
        data.setdefault("extra_rate", self.db.get_float("extra_rate", 250))
        e = DayEntry(**data)
        self.db.save_day(e)
        return True

    def _apply_payment(self, payload):
        """payment_date_entered / payment_received -> set_received(неделя, дата)."""
        week = str(payload.get("week_id") or "").strip()
        pay_date = str(payload.get("payment_date") or "").strip()
        if not week:
            return False
        try:
            monday = dt.date.fromisoformat(week)
        except ValueError:
            return False
        if self.db.week_received(monday):
            return False
        if not pay_date:
            pay_date = self.db.received_on(monday) or dt.date.today().isoformat()
        self.db.set_received(monday, pay_date)
        return True

    def _on_create_result(self, result, name):
        dlg = self._reg_dialog
        if result.get("ok") and result.get("employee_id"):
            emp_id = str(result.get("employee_id", ""))
            emp_tok = str(result.get("employee_token", ""))
            self.db.set("employee_id", emp_id)
            self.db.set("employee_token", emp_tok)
            self.db.set("secret_key", emp_tok)
            if name and not self.db.get("employee", ""):
                self.db.set("employee", name)
            if self.sync_client:
                self.sync_client.set_credentials(emp_id, emp_tok)
            if dlg is not None:
                try:
                    dlg.destroy()
                except Exception:
                    pass
            self._update_sync_panel()
            TokenDialog(self, emp_tok)
        else:
            err = str(result.get("error", "неизвестная ошибка"))
            self._sync_last_error = err
            if dlg is not None:
                dlg.show_error("Ошибка сервера: " + err)
            else:
                ui.toast(self, "Регистрация не удалась: " + err, "err")

    def _on_restore_result(self, result):
        dlg = self._restore_dialog
        if result.get("ok") and result.get("status") == "restored":
            days, weeks = self._import_server_state(result)
            if dlg is not None:
                try:
                    dlg.destroy()
                except Exception:
                    pass
            self._update_sync_panel()
            ui.toast(self, "Аккаунт восстановлен: дней %d, недель %d" % (days, weeks))
        else:
            err = str(result.get("error", "неизвестная ошибка"))
            self._sync_last_error = err
            if dlg is not None:
                dlg.show_error("Ошибка сервера: " + err)
            else:
                ui.toast(self, "Восстановление не удалось: " + err, "err")

    def _import_server_state(self, result):
        """Импорт timesheet_state / payment_state из ответа restore_account."""
        emp_id = str(result.get("employee_id", ""))
        emp_tok = str(result.get("employee_token", ""))
        if emp_id:
            self.db.set("employee_id", emp_id)
        if emp_tok:
            self.db.set("employee_token", emp_tok)
            self.db.set("secret_key", emp_tok)
        if self.sync_client and emp_id and emp_tok:
            self.sync_client.set_credentials(emp_id, emp_tok)

        days_imported = 0
        for item in result.get("timesheet_state", []) or []:
            date = str(item.get("date") or "").strip()
            try:
                version = int(item.get("version") or 1)
            except (TypeError, ValueError):
                version = 1
            payload = item.get("payload") or {}
            entry_data = payload.get("entry") or {}
            if not date or not isinstance(entry_data, dict) or not entry_data:
                continue
            local = self.db.load_day(date)
            local_version = 0 if local.is_empty else int(local.version or 1)
            if local_version >= version:
                continue
            data = dict(entry_data)
            data.pop("id", None)
            data["date"] = date
            data["version"] = version
            data["sync_status"] = "synced"
            for k in ("lunch_on", "extra_on", "extra_use_fixed", "penalty_on"):
                data.setdefault(k, False)
            data.setdefault("approved_at", local.approved_at or "")
            data.setdefault("rate", self.db.get_float("rate", 250))
            data.setdefault("extra_rate", self.db.get_float("extra_rate", 250))
            try:
                self.db.save_day(DayEntry(**data))
                days_imported += 1
            except Exception:
                continue

        weeks_imported = 0
        for item in result.get("payment_state", []) or []:
            week_id = str(item.get("week_id") or "").strip()
            payment_date = str(item.get("payment_date") or "").strip()
            confirmed = bool(item.get("payment_confirmed"))
            if not week_id or not confirmed or not payment_date:
                continue
            try:
                monday = dt.date.fromisoformat(week_id)
            except ValueError:
                continue
            if not self.db.week_received(monday):
                self.db.set_received(monday, payment_date)
                weeks_imported += 1

        self.load_date(self.current)
        self.refresh_week()
        self.refresh_history()
        self.load_settings()
        return days_imported, weeks_imported

    def _on_approved_sent(self, result):
        if result.get("ok") and result.get("status") == "synced":
            ui.toast(self, "Одобрение доставлено на телефон")
        elif result.get("ok") and result.get("status") == "conflict":
            ui.toast(self, "Сервер отклонил одобрение: запись изменилась на "
                           "телефоне (version не совпадает)", "warn")
        else:
            err = str(result.get("error", "неизвестная ошибка"))
            self._sync_last_error = err
            ui.toast(self, "Одобрено локально; сервер недоступен: " + err, "warn")

    # ---------------------------------------------------------- диалоги/панели
    def open_registration(self):
        if not (SYNC_AVAILABLE and self.sync_client):
            return
        if self._reg_dialog is not None:
            try:
                self._reg_dialog.lift()
                return
            except Exception:
                self._reg_dialog = None
        RegDialog(self)

    def open_restore(self):
        if not (SYNC_AVAILABLE and self.sync_client):
            ui.toast(self, "Синхронизация недоступна в этой сборке", "warn")
            return
        if self._restore_dialog is not None:
            try:
                self._restore_dialog.lift()
                return
            except Exception:
                self._restore_dialog = None
        RestoreDialog(self)

    def show_token(self):
        tok = self.db.get("employee_token", "") or self.db.get("secret_key", "")
        if tok:
            TokenDialog(self, tok)
        else:
            messagebox.showinfo("Токен", "Токен ещё не получен: выполните регистрацию.")

    def _update_sync_panel(self):
        lbl_dev = getattr(self, "lbl_dev", None)
        lbl_reg = getattr(self, "lbl_reg", None)
        if lbl_dev is None or lbl_reg is None:
            return
        if not (SYNC_AVAILABLE and self.sync_client):
            lbl_dev.config(text="")
            lbl_reg.config(text="Синхронизация недоступна в этой сборке",
                           fg=T["text_muted"])
            return
        lbl_dev.config(text="ID устройства: " + self.sync_client.device_id)
        emp_id, _ = self._creds()
        if emp_id:
            lbl_reg.config(text="Статус: зарегистрирован (employee_id %s…)"
                           % emp_id[:8], fg=APPROVED_COLOR)
        else:
            lbl_reg.config(text="Статус: не зарегистрирован — выполните "
                                 "первичную регистрацию", fg=T["warn"])
        if self._sync_last_error:
            lbl_reg.config(text=lbl_reg.cget("text") +
                           "  •  ошибка связи: " + self._sync_last_error)

    # ------------------------------------------------------------------ шапка
    def _build_header(self):
        head = tk.Frame(self, bg=T["accent"], height=74)
        head.pack(fill="x")
        head.pack_propagate(False)

        left = tk.Frame(head, bg=T["accent"])
        left.pack(side="left", padx=22)
        tk.Label(left, text="ТАБЕЛЬ 2.0", bg=T["accent"], fg="white",
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
        self.btn_save = ttk.Button(pad, text="СОХРАНИТЬ ДЕНЬ   (Ctrl+S)",
                                   style="Accent.TButton", command=self.save_day)
        self.btn_save.pack(fill="x")
        row2 = tk.Frame(pad, bg=T["surface"])
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text="Заполнить по умолчанию", style="Ghost.TButton",
                   command=self.fill_defaults).pack(side="left", expand=True, fill="x",
                                                    padx=(0, 4))
        self.btn_clear = ttk.Button(row2, text="Очистить день", style="Danger.TButton",
                                    command=self.clear_day)
        self.btn_clear.pack(side="left", expand=True, fill="x", padx=(4, 0))
        row3 = tk.Frame(pad, bg=T["surface"])
        row3.pack(fill="x", pady=(8, 0))
        self.btn_approve = ttk.Button(row3, text="✓  ОДОБРИТЬ ДЕНЬ",
                                      style="Ghost.TButton", command=self.approve_day)
        self.btn_approve.pack(side="left")
        self.lbl_approve = tk.Label(row3, text="", bg=T["surface"], fg=T["text_muted"],
                                    font=F_SMALL)
        self.lbl_approve.pack(side="left", padx=(12, 0))

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
        ttk.Button(bar, text="Одобрить выбранный день", style="Ghost.TButton",
                   command=self.approve_selected).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Excel: неделя", style="Ghost.TButton",
                   command=lambda: self.export("week", "xlsx")).pack(side="right", padx=(4, 10))
        ttk.Button(bar, text="PDF: неделя", style="Ghost.TButton",
                   command=lambda: self.export("week", "pdf")).pack(side="right", padx=4)
        ttk.Button(bar, text="Карточка за месяц (PDF)", style="Accent.TButton",
                   command=lambda: self.export("month", "pdf")).pack(side="right", padx=4)

        cols = ("wd", "date", "time", "hours", "xtime", "xhours", "works",
                "pay", "xpay", "bonus", "total", "appr")
        titles = ("День", "Дата", "Время работы", "Кол-во часов", "Доп. время",
                  "Доп. часы", "Объём и качество работ", "Оплата за день",
                  "Доп. работы", "Премия", "Итого", "Одобрено")
        widths = (46, 74, 118, 96, 108, 84, 300, 112, 100, 84, 110, 76)
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

        paybar = tk.Frame(root, bg=T["surface"], highlightbackground=T["border"],
                          highlightthickness=1)
        paybar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.lbl_week_pay = tk.Label(paybar, text="", bg=T["surface"], fg=T["text"],
                                     font=F_BODY_B, anchor="w", padx=12, pady=8)
        self.lbl_week_pay.pack(fill="x")

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
        vs = tk.Scrollbar(main.body, orient="vertical", command=self.htree.yview)
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

        c5 = Card(root, "Синхронизация и аккаунт")
        c5.grid(row=2, column=0, columnspan=2, sticky="new", pady=6)
        b5 = c5.body
        self.lbl_reg = tk.Label(b5, text="", bg=T["surface"], fg=T["text"],
                                font=F_BODY_B, anchor="w")
        self.lbl_reg.pack(fill="x")
        self.lbl_dev = tk.Label(b5, text="", bg=T["surface"], fg=T["text_muted"],
                                font=("Consolas", 8), anchor="w", wraplength=760,
                                justify="left")
        self.lbl_dev.pack(fill="x", pady=(2, 8))
        rowb = tk.Frame(b5, bg=T["surface"])
        rowb.pack(fill="x")
        ttk.Button(rowb, text="Регистрация (новый аккаунт)", style="Accent.TButton",
                   command=self.open_registration).pack(side="left")
        ttk.Button(rowb, text="Показать токен", style="Ghost.TButton",
                   command=self.show_token).pack(side="left", padx=(8, 0))
        ttk.Button(rowb, text="Восстановить аккаунт", style="Ghost.TButton",
                   command=self.open_restore).pack(side="left", padx=(8, 0))

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
        self._set_locked(bool(e.approved_at) or self.db.week_received(d), e)
        self.refresh_week()

    def _set_locked(self, locked, e=None):
        """Блокировка формы: день одобрен или неделя закрыта окончательно."""
        self._locked = locked
        st = "disabled" if locked else "normal"
        for w in (self.f_start.entry, self.f_end.entry, self.f_lunch.entry,
                  self.f_xstart.entry, self.f_xend.entry, self.f_xrate.entry,
                  self.f_xfixed.entry, self.f_bonus.entry,
                  self.txt_works, self.txt_xworks):
            w.config(state=st)
        for t in (self.t_lunch, self.t_extra, self.t_xfixed):
            t.cb.config(state=st)
        self.btn_save.config(state=st)
        self.btn_clear.config(state=st)

        if e is None:
            e = self.db.load_day(self.current)
        if locked and self.db.week_received(self.current):
            rec = _fmt_date_ru(self.db.received_on(self.current))
            self.lbl_approve.config(
                text="Неделя закрыта окончательно (получена %s) — запись неизменяема"
                     % (rec or "—"), fg=T["text_muted"])
            self.btn_approve.config(state="disabled")
        elif e.approved_at:
            self.lbl_approve.config(
                text="✓ Одобрено " + e.approved_at[:16].replace("T", " "),
                fg=APPROVED_COLOR)
            self.btn_approve.config(state="disabled")
        elif e.is_empty:
            self.lbl_approve.config(text="Одобрение доступно после заполнения дня",
                                    fg=T["text_muted"])
            self.btn_approve.config(state="disabled")
        else:
            self.lbl_approve.config(text="День не одобрен", fg=T["warn"])
            self.btn_approve.config(state="normal")

    def shift_day(self, n):
        self.load_date(self.current + dt.timedelta(days=n))

    def shift_week(self, n):
        self.load_date(self.current + dt.timedelta(weeks=n))

    def fill_defaults(self):
        self.f_start.set(self.db.get("default_start", "8:00"))
        self.f_end.set(self.db.get("default_end", "17:00"))
        self.recalc()

    def save_day(self):
        if getattr(self, "_locked", False):
            ui.toast(self, "Запись одобрена или неделя закрыта — изменения запрещены",
                     "warn")
            return
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
        if getattr(self, "_locked", False):
            ui.toast(self, "Запись одобрена или неделя закрыта — удаление запрещено",
                     "warn")
            return
        if messagebox.askyesno("Очистить день",
                               "Удалить запись за %02d.%02d.%d?" % (
                                   self.current.day, self.current.month, self.current.year)):
            self.db.delete_day(self.current)
            self.load_date(self.current)
            ui.toast(self, "Запись удалена", "warn")

    # ------------------------------------------------------------- одобрения
    def approve_date(self, d):
        """Локальное одобрение + отправка day_approved с текущей version."""
        e = self.db.load_day(d)
        if e.is_empty:
            ui.toast(self, "Пустой день одобрять нельзя", "warn")
            return False
        if e.approved_at:
            ui.toast(self, "День уже одобрен", "warn")
            return False
        if self.db.week_received(d):
            ui.toast(self, "Неделя закрыта окончательно — одобрение недоступно", "warn")
            return False
        self.db.mark_approved(d)
        version = self.db.get_day_version(d)
        if d == self.current:
            self.load_date(self.current)
        emp_id, emp_tok = self._creds()
        if SYNC_AVAILABLE and self.sync_client and emp_id and emp_tok:
            self.sync_client.send_async(
                "day_approved", emp_id, emp_tok, d.isoformat(), version,
                callback=lambda r: self.sync_queue.put(("approved_sent", r)))
            ui.toast(self, "День одобрен ✓ (отправлено на телефон)")
        else:
            ui.toast(self, "День одобрен ✓ (локально, без сервера)")
        return True

    def approve_day(self):
        self.approve_date(self.current)

    def approve_selected(self):
        sel = self.tree.selection()
        if not sel:
            ui.toast(self, "Выберите строку дня в таблице недели", "warn")
            return
        iid = sel[0]
        if not iid.startswith("d:"):
            ui.toast(self, "Выберите строку дня, а не итог", "warn")
            return
        d = dt.date.fromisoformat(iid[2:])
        if self.approve_date(d):
            self.refresh_week()

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
                "✓" if e.approved_at else ("—" if not e.is_empty else ""),
            ))
        t = Totals(days)
        self.tree.insert("", "end", iid="total", tags=("total",), values=(
            "", "ИТОГО", "", fmt_hm_short(t.work_min), "", fmt_hm_short(t.extra_min),
            "Отработано дней: %d   •   всего %s" % (t.worked_days, fmt_hm(t.total_min)),
            fmt_money(t.day_pay), fmt_money(t.extra_pay), fmt_money(t.bonus),
            fmt_money(t.total_pay), ""))

        self.w_tiles["days"].set(str(t.worked_days))
        self.w_tiles["hours"].set(fmt_hm(t.work_min))
        self.w_tiles["xhours"].set(fmt_hm(t.extra_min))
        self.w_tiles["bonus"].set(fmt_money(t.bonus))
        self.w_tiles["total"].set(fmt_money(t.total_pay))

        # строка выплаты: одобрено X из Y, дата получения, подпись
        filled = [e for e in days if not e.is_empty]
        appr = sum(1 for e in filled if e.approved_at)
        closed = self.db.week_received(self.current)
        rec = _fmt_date_ru(self.db.received_on(self.current))
        sig = "✓" if closed else "—"
        self.lbl_week_pay.config(
            text="Одобрено дней: %d из %d   •   Дата получения: %s   •   Подпись: %s%s"
                 % (appr, len(filled), rec or "—", sig,
                    "   •   неделя неизменяема" if closed else ""),
            fg=APPROVED_COLOR if closed else T["text"])

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
        self._update_sync_panel()

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
                _ensure_pdf_fonts()
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

    # ---------------------------------------------------------------- закрытие
    def _on_close(self):
        for aid in (self._after_poll, self._after_queue):
            if aid:
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
        self._after_poll = None
        self._after_queue = None
        try:
            if not getattr(self, "_locked", False):
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
