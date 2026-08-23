# -*- coding: utf-8 -*-
"""Смоук-тест Windows-GUI без реального дисплея (Xvfb): открыть, заполнить, сохранить."""
import os, sys, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "windows"))
sys.path.insert(0, os.path.join(HERE, "core"))
os.environ.setdefault("APPDATA", "/tmp/appdata")

import app as A

win = A.App()
win.update()
print("окно создано:", win.winfo_width(), "x", win.winfo_height())

# заполняем понедельник
win.load_date(dt.date(2026, 8, 17))
win.f_start.set("8"); win.f_end.set("17.15")
win.txt_works.delete("1.0", "end"); win.txt_works.insert("1.0", "Доски и тюльки")
win.update(); print("день 17.08:", win.tile_hours.value["text"], "|", win.lbl_total_day["text"])
win.db.save_day(win.collect())

# вторник с обедом и доп. работами
win.load_date(dt.date(2026, 8, 18))
win.f_start.set("8"); win.f_end.set("17:27")
win.t_lunch.set(True); win.toggle_lunch(); win.f_lunch.set("30")
win.t_extra.set(True); win.toggle_extra()
win.f_xstart.set("10:00"); win.f_xend.set("16:30"); win.f_xrate.set("250")
win.txt_works.delete("1.0", "end")
win.txt_works.insert("1.0", "Косьба травы, забор — натягивание сетки, опоры для кубов")
win.txt_xworks.insert("1.0", "Дополнительные работы по договорённости")
win.f_bonus.set("500")
win.update()
print("день 18.08:", win.tile_hours.value["text"], "| доп", win.tile_xhours.value["text"],
      "|", win.lbl_total_day["text"])
win.save_day()

win.nb.select(win.tab_week); win.update()
print("неделя:", win.lbl_week["text"], "| итого:", win.w_tiles["total"].value["text"],
      "| часы:", win.w_tiles["hours"].value["text"], "| доп:", win.w_tiles["xhours"].value["text"])
win.nb.select(win.tab_hist); win.update()
print("история месяцев:", win.lst_months.size())
win.nb.select(win.tab_set); win.update()
win.save_settings(); win.update()

# скриншоты вкладок
try:
    import subprocess
    for i, name in enumerate(["day", "week", "hist", "set"]):
        win.nb.select(i); win.update(); win.update_idletasks()
        subprocess.run(["import", "-window", "root", "/tmp/shot_%s.png" % name],
                       env=dict(os.environ), check=False)
except Exception as ex:
    print("скриншот пропущен:", ex)

win.nb.select(0); win.update()
print("СМОУК-ТЕСТ GUI: OK")
win.destroy()
