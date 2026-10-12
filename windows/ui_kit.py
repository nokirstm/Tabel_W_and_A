# -*- coding: utf-8 -*-
"""UI-кит для Windows-версии: стили ttk и составные виджеты."""
import tkinter as tk
from tkinter import ttk
from timecard_core import THEME as T

FONT = "Segoe UI"
# УВЕЛИЧЕННЫЕ КЕГЛИ (было 10/12/17, стало 14/16/18)
F_H1 = (FONT, 18, "bold")
F_H2 = (FONT, 16, "bold")
F_BODY = (FONT, 14)
F_BODY_B = (FONT, 15, "bold")
F_SMALL = (FONT, 11)
F_BIG_NUM = (FONT, 24, "bold")
F_MONO = ("Consolas", 12)
F_GIANT = (FONT, 20, "bold") # Для кнопок сотрудников

def install_styles(root):
    st = ttk.Style(root)
    try: st.theme_use("clam")
    except tk.TclError: pass
    root.configure(bg=T["bg"])
    
    st.configure(".", background=T["bg"], foreground=T["text"], font=F_BODY)
    st.configure("TFrame", background=T["bg"])
    st.configure("Card.TFrame", background=T["surface"], relief="flat")
    st.configure("Head.TFrame", background=T["accent"])
    st.configure("Alt.TFrame", background=T["surface_alt"])
    st.configure("TLabel", background=T["bg"], foreground=T["text"], font=F_BODY)
    st.configure("Card.TLabel", background=T["surface"], foreground=T["text"])
    st.configure("CardMuted.TLabel", background=T["surface"], foreground=T["text_muted"], font=F_SMALL)
    st.configure("H1.TLabel", background=T["accent"], foreground=T["white"], font=F_H1)
    st.configure("HSub.TLabel", background=T["accent"], foreground="#EAF3FB", font=F_SMALL)
    st.configure("H2.TLabel", background=T["surface"], foreground=T["accent_dark"], font=F_H2)
    st.configure("Big.TLabel", background=T["surface"], foreground=T["accent_dark"], font=F_BIG_NUM)
    st.configure("Money.TLabel", background=T["surface"], foreground=T["ok"], font=F_BIG_NUM)
    
    st.configure("TEntry", fieldbackground=T["white"], bordercolor=T["border"], lightcolor=T["border"], darkcolor=T["border"], insertcolor=T["text"], padding=6, font=F_BODY)
    st.map("TEntry", bordercolor=[("focus", T["accent"])])
    
    st.configure("TCheckbutton", background=T["surface"], foreground=T["text"], font=F_BODY_B, focuscolor=T["surface"])
    st.map("TCheckbutton", background=[("active", T["surface"])], indicatorcolor=[("selected", T["accent"]), ("!selected", T["white"])])
    
    st.configure("TCombobox", fieldbackground=T["white"], background=T["white"], bordercolor=T["border"], arrowcolor=T["accent_dark"], padding=6, font=F_BODY)
    
    st.configure("Accent.TButton", background=T["accent"], foreground=T["white"], font=F_BODY_B, borderwidth=0, focusthickness=0, padding=(16, 10))
    st.map("Accent.TButton", background=[("active", T["accent_dark"]), ("pressed", T["accent_dark"])])
    st.configure("Ghost.TButton", background=T["surface_alt"], foreground=T["text"], font=F_BODY, borderwidth=0, padding=(12, 8))
    st.map("Ghost.TButton", background=[("active", T["accent_light"])])
    st.configure("Nav.TButton", background=T["accent_dark"], foreground=T["white"], font=(FONT, 14, "bold"), borderwidth=0, padding=(12, 6))
    st.map("Nav.TButton", background=[("active", "#33689F")])
    st.configure("Danger.TButton", background="#E7D3D1", foreground=T["danger"], font=F_BODY, borderwidth=0, padding=(12, 8))
    st.map("Danger.TButton", background=[("active", "#DDBDB9")])
    
    # Стили для цветных заголовков таблицы (ТЗ: цвета колонок)
    st.configure("H_Main.Treeview.Heading", foreground="#2f81f1", font=F_BODY_B)
    st.configure("H_Extra.Treeview.Heading", foreground="#d762de", font=F_BODY_B)
    st.configure("H_Bonus.Treeview.Heading", foreground="#59f2ed", font=F_BODY_B)
    st.configure("H_Penalty.Treeview.Heading", foreground="#cd142e", font=F_BODY_B)
    st.configure("H_Appr.Treeview.Heading", foreground="#249d07", font=F_BODY_B)

    st.configure("Treeview", background=T["white"], fieldbackground=T["white"], foreground=T["text"], rowheight=34, borderwidth=0, font=F_BODY)
    st.configure("Treeview.Heading", background=T["accent_light"], foreground=T["accent_dark"], font=F_BODY_B, relief="flat", padding=8)
    st.map("Treeview.Heading", background=[("active", T["accent_light"])])
    st.map("Treeview", background=[("selected", T["accent"])], foreground=[("selected", T["white"])])
    
    st.configure("TNotebook", background=T["bg"], borderwidth=0, tabmargins=(6, 6, 6, 0))
    st.configure("TNotebook.Tab", background=T["surface_alt"], foreground=T["text_muted"], font=F_BODY_B, padding=(24, 10), borderwidth=0)
    st.map("TNotebook.Tab", background=[("selected", T["surface"])], foreground=[("selected", T["accent_dark"])])
    st.configure("TSeparator", background=T["border"])
    return st

class Card(tk.Frame):
    def __init__(self, master, title=None, **kw):
        kw.setdefault("bg", T["surface"])
        kw.setdefault("highlightbackground", T["border"])
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("bd", 0)
        super().__init__(master, **kw)
        self.body = self
        if title:
            head = tk.Frame(self, bg=T["surface"])
            head.pack(fill="x", padx=16, pady=(14, 0))
            tk.Label(head, text=title, bg=T["surface"], fg=T["accent_dark"], font=F_H2, anchor="w").pack(side="left")
            tk.Frame(self, bg=T["accent_light"], height=2).pack(fill="x", padx=16, pady=(8, 10))
            self.body = tk.Frame(self, bg=T["surface"])
            self.body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

class Field(tk.Frame):
    def __init__(self, master, label, width=10, hint=None, on_change=None, justify="center", font=None):
        super().__init__(master, bg=T["surface"])
        tk.Label(self, text=label, bg=T["surface"], fg=T["text_muted"], font=F_SMALL, anchor="w").pack(anchor="w")
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, width=width, font=font or F_BODY, justify=justify,
                              bg=T["white"], fg=T["text"], relief="flat", highlightthickness=1,
                              highlightbackground=T["border"], highlightcolor=T["accent"], insertbackground=T["text"])
        self.entry.pack(fill="x", ipady=6, pady=(4, 0))
        if hint:
            tk.Label(self, text=hint, bg=T["surface"], fg=T["text_muted"], font=(FONT, 9)).pack(anchor="w")
        if on_change:
            self.var.trace_add("write", lambda *a: on_change())
    def get(self): return self.var.get()
    def set(self, v): self.var.set("" if v is None else str(v))

class Toggle(tk.Frame):
    def __init__(self, master, text, command=None, bg=None):
        bg = bg or T["surface"]
        super().__init__(master, bg=bg)
        self.var = tk.BooleanVar(value=False)
        self.command = command
        self.cb = tk.Checkbutton(self, text="  " + text, variable=self.var, command=self._fire, bg=bg, fg=T["text"],
                                 activebackground=bg, activeforeground=T["accent_dark"], selectcolor=T["white"],
                                 font=F_BODY_B, anchor="w", highlightthickness=0, bd=0, cursor="hand2")
        self.cb.pack(anchor="w", fill="x")
    def _fire(self):
        if self.command: self.command()
    def get(self): return bool(self.var.get())
    def set(self, v): self.var.set(bool(v))

class StatTile(tk.Frame):
    def __init__(self, master, label, value="—", color=None, bg=None):
        bg = bg or T["surface_alt"]
        super().__init__(master, bg=bg, highlightbackground=T["border"], highlightthickness=1)
        tk.Label(self, text=label, bg=bg, fg=T["text_muted"], font=F_SMALL).pack(pady=(10, 0))
        self.value = tk.Label(self, text=value, bg=bg, fg=color or T["accent_dark"], font=(FONT, 18, "bold"))
        self.value.pack(pady=(0, 10), padx=16)
    def set(self, text): self.value.config(text=text)

def toast(root, text, kind="ok"):
    colors = {"ok": T["ok"], "warn": T["warn"], "err": T["danger"]}
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    frame = tk.Frame(win, bg=colors.get(kind, T["ok"]), padx=20, pady=12)
    frame.pack()
    tk.Label(frame, text=text, bg=colors.get(kind, T["ok"]), fg="white", font=F_BODY_B).pack()
    root.update_idletasks()
    x = root.winfo_rootx() + root.winfo_width() - win.winfo_reqwidth() - 40
    y = root.winfo_rooty() + root.winfo_height() - win.winfo_reqheight() - 40
    win.geometry("+%d+%d" % (x, y))
    win.after(2500, win.destroy)
