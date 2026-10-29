from __future__ import annotations
from datetime import date
SUFFIXES = (' PRIVATE LIMITED', ' PVT LTD', ' PVT. LTD.', ' LIMITED', ' LTD.', ' LTD')

def short_issuer(name: str | None, width: int=28) -> str:
    s = ' '.join(str(name or '').split())
    for suffix in SUFFIXES:
        if s.upper().endswith(suffix):
            s = s[:-len(suffix)]
    s = ' '.join((w if w.isupper() and len(w) <= 4 else w.capitalize() if w.isupper() else w for w in s.split()))
    return s if len(s) <= width else s[:width - 1] + '…'

def bond_label(name: str | None, coupon=None, maturity: date | None=None, width: int=28, month: bool=False) -> str:
    parts = [short_issuer(name, width)]
    if coupon is not None:
        try:
            parts.append(f'{float(coupon):.2f}%'.replace('.00%', '%'))
        except (TypeError, ValueError):
            pass
    if maturity is not None:
        parts.append(f"{maturity:%b} '{maturity:%y}" if month else f"'{maturity:%y}")
    return ' '.join((p for p in parts if p))

def real_ytm(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 0 < x < 50 else None
