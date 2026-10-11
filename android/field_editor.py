# -*- coding: utf-8 -*-
"""
Адаптер для однострочного нативного ввода (ФИО, даты).
Паттерн идентичен native_editor.py / WorksEditor.
"""
import json
import uuid
import os

from kivy.clock import Clock


class FieldEditor:
    """Открывает нативный Android EditText для однострочного поля."""

    def __init__(self):
        self._editor_cls = None
        self._poll_ev = None
        self._token = None
        self._callback = None

    def open(self, title, current, input_kind, callback):
        """
        title      — заголовок диалога
        current    — текущий текст поля
        input_kind — "text" или "number"
        callback(status, text) — вызывается в Kivy-потоке
        """
        if not os.environ.get("ANDROID_ARGUMENT"):
            # Десктоп: возвращаем текст как есть (для разработки)
            Clock.schedule_once(lambda *_: callback("ok", current), 0.1)
            return True

        try:
            from jnius import autoclass
            if self._editor_cls is None:
                # Загружаем класс ЗАРАНЕЕ в Kivy-потоке (фикс ClassNotFound)
                self._editor_cls = autoclass("org.tabel.bridge.FieldEditor")
        except Exception as ex:
            Clock.schedule_once(lambda *_: callback("error", str(ex)), 0)
            return False

        self._token = str(uuid.uuid4())
        self._callback = callback

        try:
            self._editor_cls.open(self._token, title, current or "", input_kind)
        except Exception as ex:
            Clock.schedule_once(
                lambda *_: callback("error", str(ex)), 0)
            return False

        self._poll_ev = Clock.schedule_interval(self._poll, 0.1)
        return True

    def _poll(self, _dt):
        try:
            raw = self._editor_cls.poll(50)  # 50 мс, не блокирует
        except Exception:
            raw = None
        if raw is None:
            return
        # Получили ответ
        self._stop_polling()
        try:
            data = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError):
            data = {"status": "error", "text": "bad json"}
        status = data.get("status", "error")
        text = data.get("text", "")
        cb = self._callback
        self._callback = None
        if cb:
            Clock.schedule_once(lambda *_: cb(status, text), 0)

    def _stop_polling(self):
        if self._poll_ev:
            self._poll_ev.cancel()
            self._poll_ev = None

    def close(self):
        self._stop_polling()
        self._callback = None
