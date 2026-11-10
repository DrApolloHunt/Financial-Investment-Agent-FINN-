"""Indian fiscal-year helpers. FY runs April–March: FY26 = Apr 2025–Mar 2026.

Quarter-end month -> quarter: Jun=Q1, Sep=Q2, Dec=Q3, Mar=Q4.
"""
from __future__ import annotations

import re
from typing import Optional

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_month_year(label: str) -> Optional[tuple[int, int]]:
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s*'?(\d{2,4})", label or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    y = int(m.group(2))
    if y < 100:
        y += 2000
    return MONTHS[m.group(1).lower()], y


def fy_of(month: int, year: int) -> int:
    """Fiscal year number (e.g. 26 for FY26) for a calendar month."""
    return (year + 1 if month >= 4 else year) % 100


def quarter_of_end_month(month: int) -> Optional[int]:
    return {6: 1, 9: 2, 12: 3, 3: 4}.get(month)


def quarter_label(label: str) -> Optional[str]:
    """'Sep 2025' -> 'Q2 FY26'."""
    my = parse_month_year(label)
    if not my:
        return None
    m, y = my
    q = quarter_of_end_month(m)
    if not q:
        return None
    return f"Q{q} FY{fy_of(m, y):02d}"


def quarter_discussed_on_call(label: str) -> Optional[str]:
    """Earnings call held in 'Oct 2025' discusses the quarter ending Sep 2025."""
    my = parse_month_year(label)
    if not my:
        return None
    m, y = my
    end_m = {1: 12, 2: 12, 3: 12, 4: 3, 5: 3, 6: 3, 7: 6, 8: 6, 9: 6,
             10: 9, 11: 9, 12: 9}[m]
    end_y = y - 1 if m in (1, 2, 3) and end_m == 12 else y
    return quarter_label(f"{['', 'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][end_m]} {end_y}")


def qkey(qlabel: str) -> tuple[int, int]:
    """Sortable key for 'Q2 FY26' -> (26, 2)."""
    m = re.match(r"Q(\d) FY(\d{2})", qlabel or "")
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def prev_quarter(qlabel: str) -> str:
    fy, q = qkey(qlabel)
    return f"Q4 FY{fy-1:02d}" if q == 1 else f"Q{q-1} FY{fy:02d}"


def year_ago(qlabel: str) -> str:
    fy, q = qkey(qlabel)
    return f"Q{q} FY{fy-1:02d}"
