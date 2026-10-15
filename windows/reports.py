# -- coding: utf-8 --
"""Отчёты: экспорт Excel и PDF.
PDF: A4 книжная, поля 10 мм со всех сторон, колонки в цветах графика,
галочки «Одобрено» и «Подпись» цветом #249d07.
Библиотеки openpyxl/reportlab импортируются лениво, чтобы приложение
запускалось без них, а ошибка показывалась только при экспорте."""
import datetime as dt
from timecard_core import (Totals, fmt_hm_short, fmt_money, week_start,
                           WEEKDAYS_RU_SHORT)

COLOR_MAIN = "2f81f1"
COLOR_EXTRA = "d762de"
COLOR_BONUS = "2f81f1"
COLOR_PEN = "cd142e"
COLOR_APPR = "249d07"
COLOR_TEXT = "22313F"
COLOR_MUTED = "6B7C8C"


def _fmt_date_ru(iso):
    try:
        d = dt.date.fromisoformat(str(iso))
        return "%02d.%02d.%d" % (d.day, d.month, d.year)
    except (TypeError, ValueError):
        return str(iso or "")


def _esc(text):
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


# ------------------------------------------------------------------ EXCEL
def export_xlsx(path, title, days, meta):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Табель"
    headers = ("Дата", "День", "Время работы", "Часы", "Доп. время", "Доп. часы",
               "Объём и качество работ", "Оплата за день", "Доп. работы",
               "Премия", "Штраф", "Итого", "Одобрено", "Подпись")
    hcolors = (None, None, None, None, None, None, None,
               COLOR_MAIN, COLOR_EXTRA, COLOR_BONUS, COLOR_PEN, None,
               COLOR_APPR, COLOR_APPR)
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Сотрудник: " + str(meta.get("employee", ""))])
    ws.append(["Организация: " + str(meta.get("organization", ""))])
    ws.append(["Сформировано: " + dt.datetime.now().strftime("%d.%m.%Y %H:%M")])
    ws.append([])
    ws.append(list(headers))
    hrow = ws.max_row
    for i, c in enumerate(hcolors, start=1):
        cell = ws.cell(row=hrow, column=i)
        cell.font = Font(bold=True, color=c or COLOR_TEXT)
        cell.fill = PatternFill("solid", fgColor="D6E6F4")
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
    received = meta.get("received") or {}
    buf = []
    last = days[-1].date_obj if days else None
    for e in days:
        d = e.date_obj
        if not e.is_empty:
            time_s = ("%s — %s" % (_t(e.start), _t(e.end))
                      if e.start is not None and e.end is not None else "—")
            ws.append([_fmt_date_ru(e.date), WEEKDAYS_RU_SHORT[d.weekday()],
                       time_s,
                       fmt_hm_short(e.work_min) if e.work_min else "—",
                       time_s and _xt(e) or _xt(e),
                       fmt_hm_short(e.extra_min) if e.extra_min else "—",
                       e.works.replace("\n", " "),
                       round(e.day_pay, 2), round(e.extra_pay, 2),
                       round(float(e.bonus or 0), 2), round(e.penalty_pay, 2),
                       round(e.total_pay, 2),
                       "✓" if e.approved_at else "", ""])
            r = ws.max_row
            for col, c in ((8, COLOR_MAIN), (9, COLOR_EXTRA), (10, COLOR_BONUS),
                           (11, COLOR_PEN), (13, COLOR_APPR)):
                ws.cell(row=r, column=col).font = Font(color=c)
        buf.append(e)
        if d.weekday() == 6 or d == last:
            t = Totals(buf)
            if t.worked_days:
                ws.append(["", "", "", fmt_hm_short(t.work_min), "",
                           fmt_hm_short(t.extra_min),
                           "Итого за неделю • дней: %d" % t.worked_days,
                           round(t.day_pay, 2), round(t.extra_pay, 2),
                           round(t.bonus, 2), round(t.penalty, 2),
                           round(t.total_pay, 2), "",
                           "✓" if received.get(week_start(d).isoformat()) else ""])
                r = ws.max_row
                for col in range(1, 15):
                    cell = ws.cell(row=r, column=col)
                    cell.fill = PatternFill("solid", fgColor="E3EDF7")
                    cell.font = Font(bold=True, color=cell.font.color or COLOR_TEXT)
                ws.cell(row=r, column=14).font = Font(bold=True, color=COLOR_APPR)
            buf = []
    mt = Totals(days)
    ws.append(["", "", "", fmt_hm_short(mt.work_min), "", fmt_hm_short(mt.extra_min),
               "ИТОГО • дней: %d" % mt.worked_days,
               round(mt.day_pay, 2), round(mt.extra_pay, 2), round(mt.bonus, 2),
               round(mt.penalty, 2), round(mt.total_pay, 2), "", ""])
    r = ws.max_row
    for col in range(1, 15):
        ws.cell(row=r, column=col).fill = PatternFill("solid", fgColor="C9DFF2")
        ws.cell(row=r, column=col).font = Font(bold=True, color=COLOR_TEXT)
    ws.append(["", "", "", "", "", "",
               "из них: оплата %s + доп %s + премия %s − штраф %s"
               % (fmt_money(mt.day_pay), fmt_money(mt.extra_pay),
                  fmt_money(mt.bonus), fmt_money(mt.penalty))])
    widths = (12, 6, 16, 8, 12, 8, 60, 12, 12, 10, 10, 12, 10, 10)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A6"
    wb.save(path)
    return path


def _t(minutes):
    from timecard_core import fmt_time
    return fmt_time(minutes)


def _xt(e):
    if e.extra_on and e.extra_start is not None and e.extra_end is not None:
        return "%s — %s" % (_t(e.extra_start), _t(e.extra_end))
    return "сумма" if e.extra_on and e.extra_use_fixed else "—"


# -------------------------------------------------------------------- PDF
def export_pdf(path, title, days, meta):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics

    reg = pdfmetrics.getRegisteredFontNames()
    fn = "Tab" if "Tab" in reg else "Helvetica"
    fb = "TabB" if "TabB" in reg else "Helvetica-Bold"
    c_text = colors.HexColor("#" + COLOR_TEXT)
    c_muted = colors.HexColor("#" + COLOR_MUTED)

    st_title = ParagraphStyle("t", fontName=fb, fontSize=12, leading=15, textColor=c_text)
    st_meta = ParagraphStyle("m", fontName=fn, fontSize=9, leading=12, textColor=c_muted)
    st_cell = ParagraphStyle("c", fontName=fn, fontSize=7.5, leading=9.5, textColor=c_text)
    st_cellb = ParagraphStyle("cb", fontName=fb, fontSize=7.5, leading=9.5, textColor=c_text)
    st_head = ParagraphStyle("h", fontName=fb, fontSize=8, leading=10)

    def _p(text, style, color=None):
        if color:
            return Paragraph('<font color="#%s">%s</font>' % (color, text), style)
        return Paragraph(str(text), style)

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title=title)

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(fn, 8)
        canvas.setFillColor(c_muted)
        canvas.drawCentredString(A4[0] / 2.0, 6 * mm, "Страница %d" % _doc.page)
        canvas.restoreState()

    story = [Paragraph(_esc(title), st_title),
             Paragraph("Сотрудник: %s&nbsp;&nbsp;|&nbsp;&nbsp;Организация: %s"
                       % (_esc(meta.get("employee", "")), _esc(meta.get("organization", ""))),
                       st_meta),
             Paragraph("Сформировано: " + dt.datetime.now().strftime("%d.%m.%Y %H:%M"),
                       st_meta),
             Spacer(1, 4 * mm)]
    if not days or all(e.is_empty for e in days):
        story.append(Paragraph("Нет данных за выбранный период.", st_cell))
        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
        return path

    headers = ("Дата", "День", "Часы", "Доп. часы", "Объём и качество работ",
               "Оплата за день", "Доп. работы", "Премия", "Штраф", "Итого",
               "Одобрено", "Подпись")
    hcolors = (COLOR_TEXT, COLOR_TEXT, COLOR_TEXT, COLOR_TEXT, COLOR_TEXT,
               COLOR_MAIN, COLOR_EXTRA, COLOR_BONUS, COLOR_PEN, COLOR_TEXT,
               COLOR_APPR, COLOR_APPR)
    data = [[_p(_esc(h), st_head, hcolors[i]) for i, h in enumerate(headers)]]
    cmds = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C3D2E0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D6E6F4")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    received = meta.get("received") or {}
    buf = []
    last = days[-1].date_obj

    def _money_cell(v, color, style):
        return _p(fmt_money(v), style, color) if v else _p("—", style, COLOR_MUTED)

    for e in days:
        d = e.date_obj
        if not e.is_empty:
            data.append([
                _p(_fmt_date_ru(e.date), st_cell),
                _p(WEEKDAYS_RU_SHORT[d.weekday()], st_cell),
                _p(fmt_hm_short(e.work_min) if e.work_min else "—", st_cell),
                _p(fmt_hm_short(e.extra_min) if e.extra_min else "—", st_cell),
                _p(_esc(e.works.replace("\n", " ")) or "—", st_cell),
                _money_cell(e.day_pay, COLOR_MAIN, st_cell),
                _money_cell(e.extra_pay, COLOR_EXTRA, st_cell),
                _money_cell(e.bonus, COLOR_BONUS, st_cell),
                _money_cell(e.penalty_pay, COLOR_PEN, st_cell),
                _money_cell(e.total_pay, COLOR_TEXT, st_cellb),
                _p("✓", st_cellb, COLOR_APPR) if e.approved_at else _p("", st_cell),
                _p("", st_cell)])
        buf.append(e)
        if d.weekday() == 6 or d == last:
            t = Totals(buf)
            if t.worked_days:
                idx = len(data)
                sig = "✓" if received.get(week_start(d).isoformat()) else ""
                data.append([
                    _p("", st_cellb), _p("", st_cellb),
                    _p(fmt_hm_short(t.work_min), st_cellb),
                    _p(fmt_hm_short(t.extra_min), st_cellb),
                    _p("Итого за неделю • дней: %d" % t.worked_days, st_cellb),
                    _money_cell(t.day_pay, COLOR_MAIN, st_cellb),
                    _money_cell(t.extra_pay, COLOR_EXTRA, st_cellb),
                    _money_cell(t.bonus, COLOR_BONUS, st_cellb),
                    _money_cell(t.penalty, COLOR_PEN, st_cellb),
                    _money_cell(t.total_pay, COLOR_TEXT, st_cellb),
                    _p("", st_cellb),
                    _p(sig, st_cellb, COLOR_APPR)])
                cmds.append(("BACKGROUND", (0, idx), (-1, idx),
                             colors.HexColor("#E3EDF7")))
            buf = []
    mt = Totals(days)
    idx = len(data)
    data.append([
        _p("", st_cellb), _p("", st_cellb),
        _p(fmt_hm_short(mt.work_min), st_cellb),
        _p(fmt_hm_short(mt.extra_min), st_cellb),
        _p("ИТОГО • дней: %d" % mt.worked_days, st_cellb),
        _money_cell(mt.day_pay, COLOR_MAIN, st_cellb),
        _money_cell(mt.extra_pay, COLOR_EXTRA, st_cellb),
        _money_cell(mt.bonus, COLOR_BONUS, st_cellb),
        _money_cell(mt.penalty, COLOR_PEN, st_cellb),
        _money_cell(mt.total_pay, COLOR_TEXT, st_cellb),
        _p("", st_cellb), _p("", st_cellb)])
    cmds.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#C9DFF2")))
    idx2 = len(data)
    data.append([_p("", st_cell), _p("", st_cell), _p("", st_cell), _p("", st_cell),
                 _p("из них: оплата %s + доп %s + премия %s − штраф %s"
                    % (fmt_money(mt.day_pay), fmt_money(mt.extra_pay),
                       fmt_money(mt.bonus), fmt_money(mt.penalty)), st_cell),
                 _p("", st_cell), _p("", st_cell), _p("", st_cell), _p("", st_cell),
                 _p("", st_cell), _p("", st_cell), _p("", st_cell)])
    cmds.append(("SPAN", (4, idx2), (11, idx2)))
    widths = [16 * mm, 9 * mm, 11 * mm, 11 * mm, 44 * mm, 16 * mm, 14 * mm,
              14 * mm, 14 * mm, 16 * mm, 12 * mm, 12 * mm]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(cmds))
    story.append(table)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return path
