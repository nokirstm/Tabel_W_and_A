# -*- coding: utf-8 -*-
"""Смоук-тест Android-версии (Kivy) под Xvfb: открыть все экраны, заполнить, сохранить."""
import os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "android"))
sys.path.insert(0, os.path.join(HERE, "core"))
os.environ["KIVY_NO_ARGS"] = "1"

from kivy.clock import Clock
import main as M


class TestApp(M.TabelApp):
    def get_application_config(self, *a, **k):
        return "/tmp/tabel_kivy.ini"

    @property
    def user_data_dir(self):
        os.makedirs("/tmp/tabel_kivy_data", exist_ok=True)
        return "/tmp/tabel_kivy_data"


app = TestApp()
steps = []


def run(dtx):
    from kivy.core.window import Window
    d = app.s_day
    print("экран ДЕНЬ:", d.l_wd.text, d.l_dt.text)

    d.load(dt.date(2026, 8, 18))
    d.f_start.input.text = "8"
    d.f_end.input.text = "17:27"
    d.t_lunch.set(True); d._lunch(True); d.f_lunch.input.text = "30"
    d.t_extra.set(True); d._extra(True)
    d.f_xstart.input.text = "10:00"; d.f_xend.input.text = "16:30"
    d.f_xrate.input.text = "250"
    d.txt_works.text = "Косьба травы, забор — натягивание сетки, опоры для кубов"
    d.txt_xworks.text = "Дополнительные работы"
    d.f_bonus.input.text = "500"
    d.recalc()
    print("  часы:", d.r_hours.value.text, "| доп:", d.r_xhours.value.text,
          "| итого:", d.r_total.value.text)
    print("  панель обеда развёрнута:", d.lunch_box.height > 0,
          "| панель доп. работ:", d.extra_box.height > 0)
    d.save()

    d.load(dt.date(2026, 8, 17))
    d.f_start.input.text = "8"; d.f_end.input.text = "17:15"
    d.txt_works.text = "Доски и тюльки"
    d.recalc(); d.save()
    print("  17.08 итого:", d.r_total.value.text)

    app.go("week"); Window.canvas.ask_update()
    print("экран НЕДЕЛЯ:", app.s_week.l_title.text, "| карточек:",
          len(app.s_week.body.children))
    app.go("hist")
    print("экран ИСТОРИЯ:", app.s_hist.l_title.text, "| блоков:",
          len(app.s_hist.body.children))
    app.go("set")
    app.s_set.f_rate.input.text = "250"
    app.s_set.f_emp.input.text = "Иванов И. И."
    app.s_set.save()
    print("экран НАСТРОЙКИ: ставка", app.db.get("rate"), "| работник",
          app.db.get("employee"))

    txt = M.reports.export_text(app.db.week_days(dt.date(2026, 8, 17)), "Неделя")
    print("отчёт «поделиться»:", txt.splitlines()[-1])

    # скриншоты экранов
    for key in ("day", "week", "hist", "set"):
        app.go(key)
        Clock.tick()
        try:
            Window.screenshot(name="/tmp/kv_%s.png" % key)
        except Exception as ex:
            print("   скриншот", key, "пропущен:", ex)
        Clock.tick()

    print("СМОУК-ТЕСТ ANDROID-UI: OK")
    app.stop()


Clock.schedule_once(run, 1.2)
app.run()
