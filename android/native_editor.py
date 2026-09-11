"""Kivy-thread adapter for the Java EditText dialog. No Python Java listeners."""
import json
import uuid
from kivy.clock import Clock


class NativeEditor:
    def __init__(self):
        from jnius import autoclass
        self.activity = autoclass('org.kivy.android.PythonActivity').mActivity
        self.bridge = autoclass('org.tabel.bridge.WorksEditor')
        self.pending = None
        self.event = None

    def open(self, title, text, callback):
        if self.pending:
            return False
        token = uuid.uuid4().hex
        self.pending = (token, callback)
        try:
            self.bridge.open(self.activity, title, text, token)
            self.event = Clock.schedule_interval(self._poll, 0.1)
        except Exception:
            self.pending = None
            raise
        return True

    def _poll(self, _dt):
        try:
            raw = self.bridge.poll()
            if not raw:
                return True
            result = json.loads(str(raw))
            if not self.pending or result['token'] != self.pending[0]:
                return True
            callback = self.pending[1]
            self.pending = None
            self.event = None
            callback(result['status'], result.get('text', ''))
            return False
        except Exception as ex:
            pending, self.pending = self.pending, None
            self.event = None
            if pending:
                pending[1]('error', str(ex))
            return False

    def close(self):
        if self.event:
            self.event.cancel()
            self.event = None
        self.pending = None
        self.bridge.close(self.activity)
