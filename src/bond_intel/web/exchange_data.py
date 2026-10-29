from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode
from bond_intel.insights import exchange as ix
from bond_intel.reference.taxonomy import SOVEREIGN
from bond_intel.web import db
WINDOWS = {'D1': 'Day', 'R5': '5 days', 'R22': '22 days', 'WTD': 'This week', 'MTD': 'This month', 'CUSTOM': 'Custom'}
LIST_KEYS = ('bucket', 'cat', 'mkt', 'seg', 'yrs', 'freq', 'sen', 'sec', 'type', 'agency')
YEARS = [('lt1', 'Under 1 yr', 0, 1), ('1-3', '1–3 yrs', 1, 3), ('3-5', '3–5 yrs', 3, 5), ('5-10', '5–10 yrs', 5, 10), ('10p', '10+ yrs', 10, 999)]
SEGMENT_LABEL = {'ORDER_BOOK': 'Order book', 'RFQ': 'RFQ'}

@dataclass
class Filters:
    win: str = 'D1'
    asof: date | None = None
    dfrom: date | None = None
    dto: date | None = None
    lists: dict[str, list[str]] = field(default_factory=dict)
    gov: bool = False
    ytm_min: float | None = None
    ytm_max: float | None = None
    cpn_min: float | None = None
    cpn_max: float | None = None
    stag: str = 'any'

    @classmethod
    def from_query(cls, q) -> Filters:

        def d(name):
            try:
                return date.fromisoformat(q.get(name)) if q.get(name) else None
            except ValueError:
                return None

        def fl(name):
            try:
                return float(q.get(name)) if q.get(name) not in (None, '') else None
            except ValueError:
                return None
        f = cls(win=q.get('win') if q.get('win') in WINDOWS else 'D1', asof=d('asof'), dfrom=d('from'), dto=d('to'), lists={k: [v for v in q.getlist(k) if v] for k in LIST_KEYS}, gov=q.get('gov') == '1', ytm_min=fl('ytm_min'), ytm_max=fl('ytm_max'), cpn_min=fl('cpn_min'), cpn_max=fl('cpn_max'), stag=q.get('stag') if q.get('stag') in ('yes', 'no') else 'any')
        return f

    def params(self, **override) -> list[tuple[str, str]]:
        p: list[tuple[str, str]] = []
        base = {'win': self.win, 'asof': self.asof, 'from': self.dfrom, 'to': self.dto, 'gov': '1' if self.gov else None, 'ytm_min': self.ytm_min, 'ytm_max': self.ytm_max, 'cpn_min': self.cpn_min, 'cpn_max': self.cpn_max, 'stag': None if self.stag == 'any' else self.stag}
        base.update({k: v for k, v in override.items() if k not in LIST_KEYS})
        for k, v in base.items():
            if v is None or v == '' or v is False:
                continue
            p.append((k, v.isoformat() if isinstance(v, date) else str(v)))
        for k in LIST_KEYS:
            vals = override[k] if k in override else self.lists.get(k, [])
            p += [(k, v) for v in vals or []]
        return p

    def query(self, **override) -> str:
        return urlencode(self.params(**override))

    def bond_filters(self) -> bool:
        return any((self.lists.get(k) for k in LIST_KEYS if k not in ('mkt', 'seg'))) or self.stag != 'any' or any((v is not None for v in (self.ytm_min, self.ytm_max, self.cpn_min, self.cpn_max)))

    def active(self) -> int:
        n = sum((1 for k in LIST_KEYS if self.lists.get(k)))
        n += sum((1 for v in (self.ytm_min, self.ytm_max, self.cpn_min, self.cpn_max) if v is not None))
        return n + (1 if self.gov else 0) + (1 if self.stag != 'any' else 0)
SORTS = {'value': ('Value traded', 'value_inr'), 'trades': ('Trades', 'trades'), 'qty': ('Quantity', 'qty'), 'ytm': ('YTM', 'ytm_pct'), 'maturity': ('Maturity', 'maturity_date'), 'bond': ('Bond', 'label')}
GROUPS = {'none': 'None', 'bucket': 'Rating bucket', 'cat': 'Category', 'issuer': 'Issuer', 'market': 'Market', 'year': 'Maturity year', 'sen': 'Seniority', 'sec': 'Security', 'freq': 'Coupon frequency'}
LEG_NAMES = {'BSE RFQ': 'BSE RFQ', 'BSE OB': 'BSE order book', 'NSE OB': 'NSE order book'}
LATEST_Q = ('scalar', ix.LATEST_DAY_SQL, {})

def latest_day() -> date | None:
    return db.scalar(ix.LATEST_DAY_SQL)

def window_q(f: Filters, asof: date) -> tuple:
    return ('rows', ix.WINDOW_SQL, {'kind': f.win, 'asof': asof, 'dfrom': f.dfrom, 'dto': f.dto})

def agg_q(start: date, end: date, markets=('NSE', 'BSE'), segments=('ORDER_BOOK', 'RFQ')) -> tuple:
    return ('rows', ix.AGG_SQL, {'s': start, 'e': end, 'exchanges': list(markets), 'segments': list(segments)})

def window(f: Filters) -> tuple[date, date] | None:
    asof = f.asof or latest_day()
    if asof is None:
        return None
    r = db.row(ix.WINDOW_SQL, **window_q(f, asof)[2])
    if not r or r['start_date'] is None or r['end_date'] is None or (r['start_date'] > r['end_date']):
        return None
    return (r['start_date'], r['end_date'])

def window_label(f: Filters, w: tuple[date, date] | None) -> str:
    if w is None:
        return WINDOWS[f.win]
    s, e = w
    if s == e:
        return f"{WINDOWS['D1']} · {e:%a} {e.day} {e:%b}"
    return f'{WINDOWS[f.win]} · {s.day} {s:%b} – {e.day} {e:%b}'

def aggregate(start: date, end: date, markets=('NSE', 'BSE'), segments=('ORDER_BOOK', 'RFQ')) -> list[dict]:
    return decorate(db.rows(ix.AGG_SQL, **agg_q(start, end, markets, segments)[2]))

def decorate(rows: list[dict]) -> list[dict]:
    from bond_intel.common.names import real_ytm
    from bond_intel.web import fmt
    for r in rows:
        if r.get('ytm_pct') is not None and real_ytm(r['ytm_pct']) is None:
            r['ytm_pct'] = None
        r['label'] = fmt.bond_label(r.get('issuer_name') or r.get('security_name'), r.get('coupon_pct'), r.get('maturity_date'))
        legs = sorted(r.get('legs') or [])
        segs = [s for s in ('RFQ', 'OB') if any((leg.endswith(s) for leg in legs))]
        r['where'] = ' + '.join(segs)
        r['market'] = ' + '.join((LEG_NAMES.get(x, x) for x in legs)) or '–'
    return rows

def sort_rows(rows: list[dict], key: str, desc: bool=True) -> list[dict]:
    col = SORTS.get(key, SORTS['value'])[1]
    have = [r for r in rows if r.get(col) is not None]
    none = [r for r in rows if r.get(col) is None]
    if col == 'label':
        have.sort(key=lambda r: str(r['label']).lower(), reverse=desc)
    else:
        have.sort(key=lambda r: (r[col], float(r.get('value_inr') or 0)), reverse=desc)
    return have + none

def group_key(r: dict, by: str) -> str:
    from bond_intel.web import fmt
    if by == 'bucket':
        return r.get('bucket') or 'BELOW_BBB'
    if by == 'cat':
        return r.get('category') or 'Other'
    if by == 'issuer':
        return fmt.short_issuer(r.get('issuer_name') or r.get('security_name'), 40) or 'Unknown'
    if by == 'market':
        return r.get('market') or '–'
    if by == 'year':
        return str(r['maturity_date'].year) if r.get('maturity_date') else 'Unknown'
    if by == 'sen':
        return r.get('seniority') or 'Unknown'
    if by == 'sec':
        return r.get('security') or 'Unknown'
    if by == 'freq':
        return fmt.freq(r.get('coupon_freq')).capitalize() if r.get('coupon_freq') else 'Unknown'
    return ''

def group_rows(rows: list[dict], by: str, labels: dict[str, str] | None=None) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in rows:
        k = group_key(r, by)
        g = groups.setdefault(k, {'key': k, 'label': (labels or {}).get(k, k), 'rows': [], 'value': 0.0, 'trades': 0})
        g['rows'].append(r)
        g['value'] += float(r.get('value_inr') or 0)
        g['trades'] += int(r.get('trades') or 0)
    out = list(groups.values())
    if by == 'year':
        out.sort(key=lambda g: (g['key'] == 'Unknown', g['key']))
    else:
        out.sort(key=lambda g: -g['value'])
    return out

def _years(r: dict, end: date) -> float | None:
    m = r.get('maturity_date')
    return None if m is None else (m - end).days / 365.25

def apply(rows: list[dict], f: Filters, end: date) -> list[dict]:
    L = f.lists
    out = []
    for r in rows:
        if not f.gov and (r.get('bucket') == 'SOVEREIGN' or r.get('category') in SOVEREIGN):
            continue
        if L.get('bucket') and r.get('bucket') not in L['bucket']:
            continue
        if L.get('cat') and (r.get('category') or 'Other') not in L['cat']:
            continue
        if L.get('yrs'):
            y = _years(r, end)
            if y is None or not any((lo <= y < hi for k, _, lo, hi in YEARS if k in L['yrs'])):
                continue
        ytm = float(r['ytm_pct']) if r.get('ytm_pct') is not None else None
        if f.ytm_min is not None and (ytm is None or ytm < f.ytm_min):
            continue
        if f.ytm_max is not None and (ytm is None or ytm > f.ytm_max):
            continue
        cpn = float(r['coupon_pct']) if r.get('coupon_pct') is not None else None
        if f.cpn_min is not None and (cpn is None or cpn < f.cpn_min):
            continue
        if f.cpn_max is not None and (cpn is None or cpn > f.cpn_max):
            continue
        if L.get('freq') and (r.get('coupon_freq') or '') not in L['freq']:
            continue
        if f.stag != 'any' and (r.get('staggered') or 'Unknown') != ('Yes' if f.stag == 'yes' else 'No'):
            continue
        if L.get('sen') and (r.get('seniority') or 'Unknown') not in L['sen']:
            continue
        if L.get('sec') and (r.get('security') or 'Unknown') not in L['sec']:
            continue
        if L.get('type') and (r.get('bond_type') or '') not in L['type']:
            continue
        if L.get('agency') and (r.get('rating_agency') or '') not in L['agency']:
            continue
        out.append(r)
    return out

def buckets() -> list[tuple[str, str]]:
    doc = (db.setting('ratings', {}) or {}).get('buckets') or {}
    return [(k, v['label']) for k, v in sorted(doc.items(), key=lambda kv: kv[1].get('sort', 99))]

def guard() -> dict:
    return db.setting('thin_trade_guard', {'mode': 'min_value', 'min_value_inr': 1000000, 'min_trades': 3}) or {}

def passes_guard(r: dict, g: dict) -> bool:
    mode = g.get('mode', 'min_value')
    if mode == 'min_trades':
        return (r.get('trades') or 0) >= int(g.get('min_trades', 3))
    if mode == 'none':
        return True
    return float(r.get('value_inr') or 0) >= float(g.get('min_value_inr', 1000000))

def guard_text(g: dict) -> str:
    mode = g.get('mode', 'min_value')
    if mode == 'none':
        return 'no minimum'
    if mode == 'min_trades':
        return f"at least {int(g.get('min_trades', 3))} trades"
    lakh = f"{float(g.get('min_value_inr', 1000000.0)) / 100000.0:,.1f}".rstrip('0').rstrip('.')
    return f'at least Rs {lakh} lakh traded'
