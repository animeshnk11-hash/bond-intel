from __future__ import annotations
import re
from datetime import date, datetime
from decimal import Decimal
from jinja2 import Undefined
from bond_intel.common import names
from bond_intel.config import IST

def _v(v):
    return None if isinstance(v, Undefined) else v

def _f(v) -> float | None:
    v = _v(v)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def cr(v, digits: int=2) -> str:
    x = _f(v)
    return '–' if x is None else f'Rs {x / 10000000.0:,.{digits}f} cr'

def cr_short(v) -> str:
    x = _f(v)
    if x is None:
        return '–'
    c = x / 10000000.0
    return f'Rs {c:,.1f} cr' if abs(c) >= 1 else f'Rs {x / 100000.0:,.1f} L'

def inr(v) -> str:
    x = _f(v)
    return '–' if x is None else f'Rs {x:,.0f}' if abs(x) >= 100 else f'Rs {x:,.2f}'

def pct(v, digits: int=2) -> str:
    x = _f(v)
    return '–' if x is None else f'{x:.{digits}f}%'

def delta_pct(cur, prev) -> float | None:
    a, b = (_f(cur), _f(prev))
    if a is None or not b:
        return None
    return (a / b - 1) * 100

def signed(v, digits: int=1, unit: str='%') -> str:
    x = _f(v)
    return '–' if x is None else f'{x:+.{digits}f}{unit}'

def bp(v) -> str:
    x = _f(v)
    return '–' if x is None else f'{x * 100:.0f} bp'

def num(v) -> str:
    x = _f(v)
    return '–' if x is None else f'{x:,.0f}'

def px(v, digits: int=2) -> str:
    x = _f(v)
    return '–' if x is None else f'{x:,.{digits}f}'

def day(d) -> str:
    if not d:
        return '–'
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    if isinstance(d, datetime):
        d = d.astimezone(IST).date()
    return f'{d.day} {d:%b %Y}'

def dshort(d) -> str:
    if not d:
        return '–'
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f'{d.day} {d:%b}'

def dow(d) -> str:
    if not d:
        return '–'
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f'{d:%a} {d.day} {d:%b %Y}'

def when(t) -> str:
    if not t:
        return '–'
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    return f'{t.astimezone(IST).day} {t.astimezone(IST):%b %H:%M}'

def now_iso() -> str:
    return datetime.now(IST).isoformat(timespec='seconds')

def ago(t) -> str:
    if not t:
        return 'never'
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    s = (datetime.now(IST) - t).total_seconds()
    if s < 90:
        return 'just now'
    if s < 5400:
        return f'{s / 60:.0f} min ago'
    if s < 172800:
        return f'{s / 3600:.0f} h ago'
    return f'{s / 86400:.0f} days ago'

def short_issuer(name: str | None, width: int=28) -> str:
    return names.short_issuer(name, width)

def bond_label(name, coupon=None, maturity=None, width: int=28, month: bool=False) -> str:
    return names.bond_label(_v(name), _v(coupon), _v(maturity), width, month)
FREQ = {'monthly': 'monthly', 'quarterly': 'quarterly', 'half_yearly': 'half-yearly', 'annual': 'annual', 'on_maturity': 'on maturity', 'other': 'other'}

def freq(v) -> str:
    return FREQ.get(v or '', '–')

def rating(code, agency=None) -> str:
    if not code:
        return 'Unrated'
    return f'{agency} {code}' if agency else str(code)
FILTERS = {'cr': cr, 'cr_short': cr_short, 'inr': inr, 'pct': pct, 'signed': signed, 'bp': bp, 'num': num, 'px': px, 'day': day, 'dshort': dshort, 'dow': dow, 'when': when, 'ago': ago, 'issuer': short_issuer, 'freq': freq}

def share(v, total) -> float:
    a, b = (_f(v) or 0.0, _f(total) or 0.0)
    return round(max(0.0, min(100.0, 100 * a / b)), 1) if b else 0.0

def is_num(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and (not isinstance(v, bool))

def web_url(v) -> str | None:
    v = _v(v)
    return v if isinstance(v, str) and re.match('^https?://[^\\s]+$', v, re.IGNORECASE) else None
