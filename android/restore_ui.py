"""System file picker and explicit preview/confirmation. DB stays on Kivy thread."""
import os
import threading
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from backup_restore import MAX_BYTES, parse_backup, preview, restore


class RestoreController:
    REQUEST = 4818

    def __init__(self, app):
        self.app = app
        self.busy = False
        self.bound = False
        self.stopped = False
        self.popup = None

    def _unbind(self):
        if self.bound:
            from android import activity
            activity.unbind(on_activity_result=self._result)
            self.bound = False

    def _finish(self):
        self._unbind()
        self.busy = False
        self.app._restoring = False
        if self.popup:
            self.popup.dismiss()
            self.popup = None

    def _error(self, message):
        self._finish()
        if not self.stopped:
            self.app._popup('Восстановление не выполнено', message)

    def open(self):
        if self.busy or getattr(self.app, '_backup_pending_path', None):
            return
        # Preserve any editable draft BEFORE opening an external activity.
        self.app.on_pause()
        self.busy = True
        self.app._restoring = True
        if not os.environ.get('ANDROID_ARGUMENT'):
            self._desktop_picker()
            return
        try:
            from android import activity
            from android.runnable import run_on_ui_thread
            from jnius import autoclass
            activity.bind(on_activity_result=self._result)
            self.bound = True

            @run_on_ui_thread
            def launch():
                try:
                    Intent = autoclass('android.content.Intent')
                    intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                    intent.addCategory(Intent.CATEGORY_OPENABLE)
                    # Some providers label .json as text/plain or octet-stream.
                    intent.setType('*/*')
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    autoclass('org.kivy.android.PythonActivity').mActivity.startActivityForResult(intent, self.REQUEST)
                except Exception as ex:
                    message = str(ex)
                    Clock.schedule_once(lambda _dt: self._error(message), 0)
            launch()
        except Exception as ex:
            self._error(str(ex))

    def _result(self, request, result, intent):
        if request != self.REQUEST:
            return
        # Copy URI on callback thread; do not manipulate Kivy widgets here.
        try:
            uri = str(intent.getData().toString()) if result == -1 and intent is not None and intent.getData() is not None else None
            Clock.schedule_once(lambda _dt: self._chosen(uri), 0)
        except Exception as ex:
            message = str(ex)
            Clock.schedule_once(lambda _dt: self._error(message), 0)

    def _chosen(self, uri):
        self._unbind()
        if self.stopped:
            return
        if uri is None:
            self._finish()
            return

        def read():
            try:
                from jnius import autoclass
                act = autoclass('org.kivy.android.PythonActivity').mActivity
                reader = autoclass('org.tabel.bridge.DocumentReader')
                text = str(reader.read(act, uri, MAX_BYTES))
                data = parse_backup(text.lstrip('\ufeff'))
                Clock.schedule_once(lambda _dt: self._preview(data), 0)
            except Exception as ex:
                message = str(ex)
                Clock.schedule_once(lambda _dt: self._error(message), 0)
        threading.Thread(target=read, daemon=True).start()

    def _desktop_picker(self):
        from kivy.uix.filechooser import FileChooserListView
        chooser = FileChooserListView(path=os.path.expanduser('~'), filters=['*.json'])
        body = BoxLayout(orientation='vertical')
        body.add_widget(chooser)
        buttons = BoxLayout(size_hint_y=None, height=dp(48))
        select = Button(text='Открыть', font_name='Regular')
        cancel = Button(text='Отмена', font_name='Regular')
        buttons.add_widget(select); buttons.add_widget(cancel); body.add_widget(buttons)
        self.popup = Popup(title='JSON', content=body, auto_dismiss=False)
        def choose(*_):
            if not chooser.selection:
                return
            try:
                with open(chooser.selection[0], 'rb') as source:
                    data = parse_backup(source.read(MAX_BYTES + 1))
                self.popup.dismiss(); self.popup = None
                self._preview(data)
            except Exception as ex:
                self._error(str(ex))
        select.bind(on_release=choose)
        cancel.bind(on_release=lambda *_: self._finish())
        self.popup.open()

    def _preview(self, data):
        if self.stopped:
            return
        try:
            p = preview(self.app.db, data)
        except Exception as ex:
            self._error(str(ex)); return
        self.pending_data = p['data']
        mode = ('Настройки и статусы недель будут восстановлены.' if p['settings'] else
                'Существующие записи и настройки останутся без изменений.\nЗакрытые недели пропускаются.')
        message = ('В копии: %d записей\nПериод: %s — %s\nБудет добавлено: %d\nПропущено: %d\n\n%s\n\n'
                   'Подтвердите, что это ваша резервная копия.\nПеред импортом создаётся защитная копия БД.'
                   % (p['total'], p['first'], p['last'], len(p['rows']), p['skipped'], mode))
        body = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(10))
        label = Label(text=message, font_name='Regular', halign='left', valign='top')
        label.bind(size=lambda w, size: setattr(w, 'text_size', size))
        body.add_widget(label)
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        apply = Button(text='Восстановить', font_name='Regular')
        cancel = Button(text='Отмена', font_name='Regular')
        apply.bind(on_release=lambda *_: self._apply())
        cancel.bind(on_release=lambda *_: self._finish())
        row.add_widget(apply); row.add_widget(cancel); body.add_widget(row)
        self.popup = Popup(title='Восстановление из копии', title_font='Regular',
                           content=body, size_hint=(.96, .85), auto_dismiss=False)
        self.popup.open()

    def _apply(self):
        if not self.busy:
            return
        try:
            result = restore(self.app.db, self.pending_data)
        except Exception as ex:
            self._error(str(ex)); return
        # Do not report an import failure if only UI refresh fails after commit.
        try:
            self.app.s_set.load()
            self.app.s_day.load(self.app.current)
            self.app.s_week.refresh()
            self.app.s_hist.refresh()
        except Exception:
            from kivy.logger import Logger
            Logger.exception('Restore: refresh failed after successful commit')
        finally:
            self._finish()
        self.app._popup('Копия восстановлена', 'Добавлено: %d\nПропущено: %d\nЗащитная копия БД сохранена в каталоге приложения.'
                        % (result['added'], result['skipped']))

    def close(self):
        self.stopped = True
        self._finish()
