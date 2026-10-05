"""Pull a date window out of a query. Calendar words only — not topic translations."""

from __future__ import annotations

import calendar
import re
from datetime import date

# Finite closed set (month names), not an open translation dictionary.
_MONTHS: dict[str, int] = {}
for i, names in enumerate(
    (
        "january januar janvier enero gennaio janeiro januari tammikuu stycznia styczeń январь يناير كانون",
        "february februar février febrero febbraio fevereiro februari helmikuu luty февраль فبراير شباط",
        "march märz maerz mars marzo março maart maaliskuu marca март مارس آذار",
        "april avril abril aprile april huhtikuu kwietnia апрель أبريل نيسان",
        "may mai mayo maggio maio mei toukokuu maja май مايو أيار",
        "june juni juin junio giugno junho kesäkuu czerwca июнь يونيو حزيران",
        "july juli juillet julio luglio julho heinäkuu lipca июль يوليو تموز",
        "august august augusti août agosto agosto elokuu sierpnia август أغسطس آب",
        "september septembre septiembre settembre setembro syyskuu września сентябрь سبتمبر أيلول",
        "october oktober octobre octubre ottobre outubro lokakuu października октябрь أكتوبر تشرين",
        "november novembre noviembre novembre novembro marraskuu listopada ноябрь نوفمبر",
        "december dezember décembre diciembre dicembre dezembro joulukuu grudnia декабрь ديسمبر كانون",
    ),
    start=1,
):
    for n in names.split():
        _MONTHS[n.casefold()] = i

_YEAR = re.compile(r"\b(20\d{2})\b")
_ISO_MONTH = re.compile(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])\b")
_ISO_DAY = re.compile(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b")
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def parse_when(text: str | None) -> tuple[date | None, date | None]:
    """Return (start, end) inclusive, or (None, None)."""
    if not text:
        return None, None
    raw = text.strip()
    m = _ISO_DAY.search(raw)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, d
    m = _ISO_MONTH.search(raw)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])

    years = [int(y) for y in _YEAR.findall(raw)]
    months = []
    for tok in _TOKEN.findall(raw):
        mo = _MONTHS.get(tok.casefold())
        if mo:
            months.append(mo)

    if years and months:
        y, mo = years[0], months[0]
        return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])
    if years and not months:
        y = years[0]
        return date(y, 1, 1), date(y, 12, 31)
    return None, None
