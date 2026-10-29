from __future__ import annotations
import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.datastructures import QueryParams
from bond_intel.common.names import real_ytm
from bond_intel.insights import exchange as ix
from bond_intel.reference.taxonomy import BOND_TYPES, CATEGORIES, COUPON_FREQS, SECURITY, SENIORITY
from bond_intel.web import auth, charts, db, fmt
from bond_intel.web import exchange_data as xd
from bond_intel.web.app import flash, page
router = APIRouter()
TABS = {'top': 'Top traded', 'yield': 'Highest yield', 'trend': 'Trend'}
METRICS = {'value': 'Value', 'trades': 'Trades', 'bonds': 'Bonds'}
PAGE_SIZES = (10, 25, 50)
LEGS = [('BSE', 'RFQ', 'BSE RFQ', charts.SERIES[0]), ('BSE', 'ORDER_BOOK', 'BSE order book', charts.SERIES[1]), ('NSE', 'ORDER_BOOK', 'NSE order book', charts.SERIES[2])]
MARKETS = ('NSE', 'BSE')
SEGMENTS = ('ORDER_BOOK', 'RFQ')
_DAY_WHERE = '\n WHERE trade_date BETWEEN :s AND :e AND exchange = ANY(:ex) AND segment = ANY(:seg)\n   AND (CAST(:every AS boolean) OR isin = ANY(CAST(:isins AS bpchar[])))\n   AND (CAST(:gov AS boolean) OR NOT sovereign)\n'
LEG_SQL = f'\nSELECT exchange, segment, sum(value_inr) AS value_inr, sum(trades) AS trades,\n       sum(ytm_pct * value_inr) FILTER (WHERE ytm_pct > 0 AND ytm_pct < 50) AS ytm_w,\n       sum(value_inr) FILTER (WHERE ytm_pct > 0 AND ytm_pct < 50) AS ytm_v\n  FROM mkt.v_trade_leg {_DAY_WHERE} GROUP BY 1, 2\n'
DAY_LEG_SQL = f'\nSELECT trade_date, exchange, segment, sum(value_inr) AS value_inr, sum(trades) AS trades, count(*) AS bonds\n  FROM mkt.v_trade_leg {_DAY_WHERE} GROUP BY 1, 2, 3 ORDER BY 1\n'
DAY_SQL = f'\nSELECT trade_date, sum(value_inr) AS value_inr, sum(trades) AS trades, count(DISTINCT isin) AS bonds\n  FROM mkt.v_trade_leg {_DAY_WHERE} GROUP BY 1 ORDER BY 1\n'
DAYS_IN_SQL = 'SELECT count(DISTINCT trade_date) FROM mkt.trade_daily WHERE trade_date BETWEEN :s AND :e'
HIST_MIN_SQL = 'SELECT min(trade_date) FROM mkt.trade_daily'
DAYS_TO_SQL = 'SELECT DISTINCT trade_date FROM mkt.trade_daily WHERE trade_date <= :e ORDER BY 1'
TRADING_DAYS_SQL = 'SELECT DISTINCT trade_date FROM mkt.trade_daily ORDER BY trade_date DESC LIMIT :n'
PROFILE_SQL = 'SELECT p.*, i.coupon_basis, i.ratings FROM ref.v_bond_profile p JOIN ref.instrument i USING (isin) WHERE p.isin = :i'
AI_SQL = 'SELECT ai_px100 FROM mkt.trade_daily WHERE isin = :i AND ai_px100 IS NOT NULL ORDER BY trade_date DESC LIMIT 1'
LAST22_SQL = 'SELECT d.trade_date, coalesce(sum(l.value_inr), 0) AS value_inr FROM (SELECT DISTINCT trade_date FROM mkt.trade_daily WHERE trade_date <= :e ORDER BY trade_date DESC LIMIT 22) d LEFT JOIN mkt.v_trade_leg l ON l.trade_date = d.trade_date AND l.isin = :i GROUP BY 1 ORDER BY 1'

class State:

    def __init__(self, request: Request):
        q = request.query_params
        self.q = q
        self.f = xd.Filters.from_query(q)
        self.tab = q.get('tab') if q.get('tab') in TABS else 'top'
        self.sort = q.get('sort') if q.get('sort') in xd.SORTS else 'value'
        self.desc = q.get('dir', 'desc') != 'asc'
        self.group = q.get('group') if q.get('group') in xd.GROUPS else 'none'
        self.by = 'cat' if q.get('by') == 'cat' else 'bucket'
        self.metric = q.get('metric') if q.get('metric') in METRICS else 'value'
        self.n = int(q.get('n')) if q.get('n', '').isdigit() and int(q.get('n')) in PAGE_SIZES else 10
        self.page = max(1, int(q.get('page'))) if q.get('page', '').isdigit() else 1
        self.gshow = q.get('gshow') or ''
        self.bond = (q.get('bond') or '').strip().upper()[:12]
        self.window = xd.window(self.f)
        self.markets = [m for m in self.f.lists.get('mkt', []) if m in MARKETS] or list(MARKETS)
        self.segments = [s for s in self.f.lists.get('seg', []) if s in SEGMENTS] or list(SEGMENTS)
        self.all_rows: list[dict] = []
        self.rows: list[dict] = []
        if self.window:
            s, e = self.window
            db.warm(*self._prefetch(s, e))
            self.all_rows = xd.aggregate(s, e, self.markets, self.segments)
            self.rows = xd.apply(self.all_rows, self.f, e)

    def legs_params(self, s: date, e: date, isins: list[str] | None=None) -> dict:
        every = not self.f.bond_filters()
        return {'s': s, 'e': e, 'ex': self.markets, 'seg': self.segments, 'every': every, 'isins': [] if every else isins or [], 'gov': self.f.gov}

    def _prefetch(self, s: date, e: date) -> list[tuple]:
        qs = [xd.agg_q(s, e, self.markets, self.segments)]
        every = not self.f.bond_filters()
        if every:
            qs.append(('rows', LEG_SQL, self.legs_params(s, e)))
        if self.tab == 'trend':
            qs += [('scalar', DAYS_IN_SQL, {'s': s, 'e': e}), ('rows', DAYS_TO_SQL, {'e': e})]
            if every:
                if s < e:
                    qs += [('rows', DAY_LEG_SQL, self.legs_params(s, e)), ('rows', DAY_SQL, self.legs_params(s, e))]
                hist_s = db.scalar(HIST_MIN_SQL)
                if hist_s:
                    qs.append(('rows', DAY_SQL, self.legs_params(hist_s, e)))
        if self.bond:
            qs += [('rows', PROFILE_SQL, {'i': self.bond}), ('rows', ix.LEGS_OF_ISIN_SQL, {'isin': self.bond, 's': s, 'e': e}), ('scalar', AI_SQL, {'i': self.bond}), ('rows', LAST22_SQL, {'e': e, 'i': self.bond})]
        return qs

    def link(self, **kw) -> str:
        base = {'tab': self.tab, 'sort': self.sort, 'dir': 'desc' if self.desc else 'asc', 'group': self.group, 'by': self.by, 'metric': self.metric, 'n': self.n}
        base.update(kw)
        defaults = {'tab': 'top', 'sort': 'value', 'dir': 'desc', 'group': 'none', 'by': 'bucket', 'metric': 'value', 'n': 10, 'page': 1}
        extra = [(k, str(v)) for k, v in base.items() if v not in (None, '') and defaults.get(k) != v]
        return '/exchange?' + urlencode(self.f.params() + extra)

    @property
    def isins(self) -> list[str]:
        return [str(r['isin']).strip() for r in self.rows]

def _leg_split(st: State) -> tuple[list[dict], float | None]:
    if not st.rows:
        return ([], None)
    s, e = st.window
    got = {(r['exchange'], r['segment']): r for r in db.rows(LEG_SQL, **st.legs_params(s, e, st.isins))}
    legs = [{'name': name, 'color': color, 'value': float((got.get((x, g)) or {}).get('value_inr') or 0)} for x, g, name, color in LEGS if (x, g) in got]
    rfq = got.get(('BSE', 'RFQ'))
    avg_rfq = float(rfq['ytm_w']) / float(rfq['ytm_v']) if rfq and rfq['ytm_v'] else None
    total = sum((x['value'] for x in legs)) or 1.0
    for x in legs:
        x['share'] = x['value'] / total * 100
    return (legs, avg_rfq)

def _facets(st: State) -> dict[str, dict[str, int]]:
    if not st.window:
        return {}
    e = st.window[1]
    out: dict[str, dict[str, int]] = {}
    for key in ('bucket', 'cat', 'yrs', 'freq', 'sen', 'sec', 'type', 'agency'):
        lists = dict(st.f.lists)
        lists[key] = []
        g = xd.Filters(**{**st.f.__dict__, 'lists': lists})
        if key == 'bucket':
            g.gov = True
        rows = xd.apply(st.all_rows, g, e)
        if key == 'bucket' and (not st.f.gov):
            rows = [r for r in rows if r['bucket'] != 'SOVEREIGN']
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            if key == 'bucket':
                counts[r['bucket']] += 1
            elif key == 'cat':
                counts[r.get('category') or 'Other'] += 1
            elif key == 'yrs':
                m = r.get('maturity_date')
                if m:
                    y = (m - e).days / 365.25
                    for k, _, lo, hi in xd.YEARS:
                        if lo <= y < hi:
                            counts[k] += 1
            elif key == 'freq':
                counts[r.get('coupon_freq') or ''] += 1
            elif key == 'sen':
                counts[r.get('seniority') or 'Unknown'] += 1
            elif key == 'sec':
                counts[r.get('security') or 'Unknown'] += 1
            elif key == 'type':
                counts[r.get('bond_type') or ''] += 1
            elif key == 'agency':
                counts[r.get('rating_agency') or ''] += 1
        out[key] = dict(counts)
    return out

def _options(st: State) -> dict[str, list[tuple[str, str]]]:
    gov = ('G-Sec', 'SDL', 'T-Bill', 'SGB')
    return {'bucket': [(k, lbl if k in ('BELOW_BBB', 'SOVEREIGN') else k) for k, lbl in xd.buckets() if st.f.gov or k != 'SOVEREIGN'], 'cat': [(c, c) for c in CATEGORIES if st.f.gov or c not in gov], 'yrs': [(k, lbl) for k, lbl, _lo, _hi in xd.YEARS], 'freq': [(k, fmt.freq(k).capitalize()) for k in COUPON_FREQS], 'sen': [(x, x) for x in SENIORITY], 'sec': [(x, x) for x in SECURITY], 'type': [(x, x) for x in BOND_TYPES], 'agency': [(a, a) for a in sorted({r['rating_agency'] for r in st.all_rows if r.get('rating_agency')})]}

def _trading_days(limit: int=90) -> list[date]:
    return [r['trade_date'] for r in db.rows(TRADING_DAYS_SQL, n=limit)]

def _top_tab(st: State) -> dict:
    ranked = xd.sort_rows(st.rows, st.sort, st.desc)
    labels = dict(xd.buckets())
    if st.group == 'none':
        pages = max(1, -(-len(ranked) // st.n))
        pg = min(st.page, pages)
        shown = ranked[(pg - 1) * st.n:pg * st.n]
        groups = [{'key': '', 'label': '', 'rows': shown, 'count': len(ranked)}]
    else:
        pages, pg = (1, 1)
        groups = xd.group_rows(ranked, st.group, labels)
        for g in groups:
            g['count'] = len(g['rows'])
            g['all'] = g['key'] == st.gshow
            if not g['all']:
                g['rows'] = g['rows'][:3]
    page_rows = [r for g in groups for r in g['rows']]
    vmax = max((float(r['value_inr'] or 0) for r in page_rows), default=1) or 1
    lows = [float(r['low_clean']) for r in page_rows if r.get('low_clean') is not None]
    highs = [float(r['high_clean']) for r in page_rows if r.get('high_clean') is not None]
    lo, hi = (min(lows), max(highs)) if lows and highs else (0.0, 1.0)
    for r in page_rows:
        if r.get('low_clean') is not None and r.get('high_clean') is not None and (hi > lo):
            a, b = (float(r['low_clean']), float(r['high_clean']))
            r['rng'] = ((a - lo) / (hi - lo) * 100, max((b - a) / (hi - lo) * 100, 2.0))
        elif r.get('low_clean') is not None:
            r['rng'] = (50.0, 2.0)
    return {'groups': groups, 'vmax': vmax, 'pages': pages, 'pg': pg, 'total': len(ranked)}

def _yield_tab(st: State) -> dict:
    guard = xd.guard()
    with_yield = [r for r in st.rows if r['ytm_pct'] is not None and 0 < float(r['ytm_pct']) < 50]
    ok = [r for r in with_yield if xd.passes_guard(r, guard)]
    if st.by == 'bucket':
        order = [(k, lbl) for k, lbl in xd.buckets() if st.f.gov or k != 'SOVEREIGN']
        key = lambda r: r['bucket']
    else:
        order = [(c, c) for c in CATEGORIES if st.f.gov or c not in ('G-Sec', 'SDL', 'T-Bill', 'SGB')]
        key = lambda r: r.get('category') or 'Other'
    groups = []
    for k, lbl in order:
        rs = sorted([r for r in ok if key(r) == k], key=lambda r: -float(r['ytm_pct']))
        if rs:
            groups.append({'key': k, 'label': lbl, 'rows': rs[:3], 'count': len(rs)})
    return {'groups': groups, 'guard': guard, 'guard_text': xd.guard_text(guard), 'qualify': len(ok), 'with_yield': len(with_yield)}

def _trend_tab(st: State) -> dict:
    s, e = st.window
    trend_f = st.f
    note = None
    days_in = db.scalar(DAYS_IN_SQL, s=s, e=e) or 0
    if days_in < 2:
        trend_f = xd.Filters(**{**st.f.__dict__, 'win': 'R22', 'asof': e})
        s, e = xd.window(trend_f) or (s, e)
        note = 'A one-day window has no trend, so this shows the last 22 trading days to it.'
    every = not st.f.bond_filters()
    if every:
        isins: list[str] = []
    else:
        rows = st.rows if (s, e) == st.window else xd.apply(xd.aggregate(s, e, st.markets, st.segments), st.f, e)
        isins = [str(r['isin']).strip() for r in rows]
    q = st.legs_params(s, e, isins)
    per = db.rows(DAY_LEG_SQL, **q) if every or isins else []
    all_days = [r['trade_date'] for r in db.rows(DAYS_TO_SQL, e=e)]
    days = [d for d in all_days if s <= d <= e] if every or isins else []
    daily = _by_day(days, db.rows(DAY_SQL, **q) if every or isins else [])
    col = {'value': 'value_inr', 'trades': 'trades', 'bonds': 'bonds'}[st.metric]
    scale = 10000000.0 if st.metric == 'value' else 1
    vfmt = (lambda v: f'Rs {v:,.1f} cr') if st.metric == 'value' else lambda v: f'{v:,.0f}'
    legs_present = [(x, g, name, color) for x, g, name, color in LEGS if any((p['exchange'] == x and p['segment'] == g for p in per))]
    if st.metric == 'bonds':
        series = [{'name': 'Bonds traded', 'values': [float(daily[d]['bonds']) for d in days], 'color': charts.SERIES[0]}]
    else:
        by = {(p['trade_date'], p['exchange'], p['segment']): float(p[col] or 0) / scale for p in per}
        series = [{'name': name, 'color': color, 'values': [by.get((d, x, g), 0.0) for d in days]} for x, g, name, color in legs_present]
    tips = []
    for i, d in enumerate(days):
        tot = daily[d]
        rows_t = [(sr['name'], sr['color'], vfmt(sr['values'][i])) for sr in series] if st.metric != 'bonds' else [('Bonds traded', charts.SERIES[0], fmt.num(tot['bonds']))]
        head = vfmt(float(tot[col] or 0) / scale)
        tips.append(charts.tip(f'{fmt.dow(d)} · {head}', rows_t, f"{fmt.num(tot['trades'])} trades · {fmt.num(tot['bonds'])} bonds"))
    chart = charts.columns([fmt.dshort(d) for d in days], series, width=1100, height=300, fmt=vfmt, tick_labels=day_ticks(days), tips=tips, tick_fmt=lambda v: f'{v:,.0f}', aria=f'{METRICS[st.metric]} per trading day')
    vals = [(d, float(daily[d][col] or 0)) for d in days]
    stats = None
    if vals:
        busiest = max(vals, key=lambda x: x[1])
        quietest = min(vals, key=lambda x: x[1])
        avg = sum((v for _, v in vals)) / len(vals)
        stats = {'avg': avg, 'busiest': busiest, 'quietest': quietest}
    hist_s = db.scalar(HIST_MIN_SQL)
    if every:
        hist = db.rows(DAY_SQL, **st.legs_params(hist_s, e)) if hist_s else []
    else:
        hist_rows = xd.apply(xd.aggregate(hist_s, e, st.markets, st.segments), st.f, e) if hist_s else []
        hq = st.legs_params(hist_s, e, [str(r['isin']).strip() for r in hist_rows])
        hist = db.rows(DAY_SQL, **hq) if hq['isins'] else []
    hist = list(_by_day(all_days, hist).values()) if hist else []
    weeks, months = _periods(hist, col, e)
    return {'chart': chart, 'series': series, 'days': days, 'stats': stats, 'vfmt': vfmt, 'scale': scale, 'note': note, 'trend_window': (s, e), 'weeks': weeks, 'months': months, 'col': col}

def _by_day(days: list[date], rows: list[dict]) -> dict[date, dict]:
    got = {r['trade_date']: r for r in rows}
    return {d: got.get(d) or {'trade_date': d, 'value_inr': 0, 'trades': 0, 'bonds': 0} for d in days}

def day_ticks(days: list[date], most: int=24) -> list[str]:
    n = len(days)
    step = max(1, -(-n // most))
    out, last_month = ([], None)
    for i, d in enumerate(days):
        if (n - 1 - i) % step:
            out.append('')
            continue
        long = (d.year, d.month) != last_month
        out.append(f'{d.day} {d:%b}' if long else str(d.day))
        last_month = (d.year, d.month)
    return out

def _periods(hist: list[dict], col: str, end: date) -> tuple[list[dict], list[dict]]:
    hol = {d: v for d, v in _holiday_names().items()}
    missing = defaultdict(list)
    for r in db.rows("SELECT trade_date, feed FROM mkt.v_feed_day WHERE status = 'missing' ORDER BY 1"):
        missing[r['trade_date']].append(r['feed'])

    def build(keyf, labelf, periodf) -> list[dict]:
        acc: dict = {}
        for r in hist:
            k = keyf(r['trade_date'])
            a = acc.setdefault(k, {'key': k, 'days': 0, 'total': 0.0, 'first': r['trade_date']})
            a['days'] += 1
            a['total'] += float(r[col] or 0)
            a['last'] = r['trade_date']
        out = sorted(acc.values(), key=lambda a: a['key'])
        prev = None
        for a in out:
            a['avg'] = a['total'] / a['days'] if a['days'] else None
            a['vs'] = fmt.delta_pct(a['avg'], prev['avg']) if prev else None
            a['label'] = labelf(a)
            lo, hi = periodf(a['key'])
            a['notes'] = [f'{d.day} {d:%b} {name}' for d, name in hol.items() if lo <= d <= hi and d.weekday() < 5]
            a['notes'] += [f"{d.day} {d:%b} {', '.join((FEED_NAMES.get(x, x) for x in fs))} data missing" for d, fs in sorted(missing.items()) if lo <= d <= hi]
            a['to_date'] = lo <= end <= hi and hi > end
            prev = a
        return out[::-1]
    weeks = build(lambda d: d - timedelta(days=d.weekday()), lambda a: f"{a['key'].day} {a['key']:%b} – {(a['key'] + timedelta(days=4)).day} {a['key'] + timedelta(days=4):%b}", lambda k: (k, k + timedelta(days=4)))
    months = build(lambda d: d.replace(day=1), lambda a: f"{a['key']:%b %Y}", lambda k: (k, (k.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)))
    return (weeks[:6], months[:4])
FEED_NAMES = {'nse_cm_udiff': 'NSE', 'bse_fgroup': 'BSE order book', 'bse_rfq': 'RFQ'}

def _holiday_names() -> dict[date, str]:
    doc = db.setting('holidays', {}) or {}
    return {date.fromisoformat(v['date']): 'market holiday' for v in doc.values() if v.get('kind') == 'trading'}

def _bond(st: State) -> dict | None:
    isin = st.bond
    if not isin or not st.window:
        return None
    s, e = st.window
    prof = db.row(PROFILE_SQL, i=isin)
    missing = prof is None
    prof = prof or {'isin': isin}
    legs = db.rows(ix.LEGS_OF_ISIN_SQL, isin=isin, s=s, e=e)
    by_leg: dict[tuple, dict] = {}
    for x in legs:
        k = (x['exchange'], x['segment'])
        a = by_leg.setdefault(k, {'exchange': x['exchange'], 'segment': x['segment'], 'value': 0.0, 'trades': 0, 'qty': 0, 'lo_c': None, 'hi_c': None, 'lo_d': None, 'hi_d': None, 'ytm': None})
        a['value'] += float(x['value_inr'] or 0)
        a['trades'] += int(x['trades'] or 0)
        a['qty'] += int(x['qty'] or 0)
        for lo, hi, src_lo, src_hi in (('lo_c', 'hi_c', 'low_clean', 'high_clean'), ('lo_d', 'hi_d', 'low_dirty', 'high_dirty')):
            if x[src_lo] is not None:
                a[lo] = min(float(x[src_lo]), a[lo]) if a[lo] is not None else float(x[src_lo])
            if x[src_hi] is not None:
                a[hi] = max(float(x[src_hi]), a[hi]) if a[hi] is not None else float(x[src_hi])
        y = real_ytm(x['ytm_pct'])
        if a['ytm'] is None and y is not None:
            a['ytm'] = y
    legs_out = []
    for x, g, name, _c in LEGS:
        if (x, g) in by_leg:
            legs_out.append({**by_leg[x, g], 'name': name})
    ai = db.scalar(AI_SQL, i=isin)
    last22 = db.rows(LAST22_SQL, e=e, i=isin)
    spark = charts.sparkbars([float(r['value_inr']) / 10000000.0 for r in last22], [fmt.dow(r['trade_date']) for r in last22], fmt=lambda v: f'Rs {v:,.2f} cr', width=320, height=70)
    prof['label'] = fmt.bond_label(prof.get('issuer_name') or prof.get('description'), prof.get('coupon_pct'), prof.get('maturity_date'), 40) or isin
    return {'p': prof, 'missing': missing, 'legs': legs_out, 'ai': ai, 'spark': spark, 'last22': last22, 'total22': sum((float(r['value_inr']) for r in last22)), 'window': (s, e)}

@router.get('/exchange', response_class=HTMLResponse)
def exchange(request: Request):
    user = auth.require_user(request)
    from bond_intel.web.app import LAYOUT_Q
    db.warm(xd.LATEST_Q, LAYOUT_Q, db.SETTINGS_Q, ('rows', TRADING_DAYS_SQL, {'n': 90}), ('scalar', HIST_MIN_SQL, {}))
    st = State(request)
    ctx: dict = {'st': st, 'tabs': TABS, 'metrics': METRICS, 'sorts': xd.SORTS, 'groups_opts': xd.GROUPS, 'page_sizes': PAGE_SIZES, 'window_label': xd.window_label(st.f, st.window), 'windows': xd.WINDOWS, 'legs_meta': LEGS, 'open_filters': request.query_params.get('filters') == '1', 'saved': _saved_filters(), 'query': request.url.query, 'opts': _options(st)}
    if st.window:
        ctx['legs'], ctx['avg_rfq'] = _leg_split(st)
        ctx['value'] = sum((float(r['value_inr'] or 0) for r in st.rows))
        ctx['trades'] = sum((int(r['trades'] or 0) for r in st.rows))
        ctx['facets'] = _facets(st)
        ctx['trading_days'] = _trading_days()
        if st.tab == 'top':
            ctx['top'] = _top_tab(st)
        elif st.tab == 'yield':
            ctx['yl'] = _yield_tab(st)
        else:
            ctx['tr'] = _trend_tab(st)
        ctx['bond'] = _bond(st)
    return page(request, 'exchange.html', 'exchange', user, **ctx)

@router.get('/exchange/count')
def exchange_count(request: Request):
    auth.require_user(request)
    st = State(request)
    return JSONResponse({'bonds': len(st.rows), 'window': xd.window_label(st.f, st.window)})

@router.get('/exchange/download.csv')
def exchange_download(request: Request):
    auth.require_user(request)
    st = State(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    s, e = st.window or (None, None)
    if st.tab == 'trend' and st.window:
        tr = _trend_tab(st)
        w.writerow(['trade_date'] + [x['name'] for x in tr['series']])
        for i, d in enumerate(tr['days']):
            w.writerow([d.isoformat()] + [round(x['values'][i] * (tr['scale'] if st.metric == 'value' else 1), 2) for x in tr['series']])
    else:
        rows = st.rows
        if st.tab == 'yield':
            yl = _yield_tab(st)
            rows = [r for g in yl['groups'] for r in g['rows']]
        else:
            rows = xd.sort_rows(rows, st.sort, st.desc)
        cols = ['isin', 'label', 'issuer_name', 'category', 'bucket', 'rating_agency', 'rating_code', 'coupon_pct', 'coupon_freq', 'maturity_date', 'seniority', 'security', 'bond_type', 'value_inr', 'trades', 'qty', 'days_traded', 'low_clean', 'high_clean', 'ytm_pct', 'legs']
        w.writerow(cols)
        for r in rows:
            w.writerow([';'.join(r[c]) if c == 'legs' and r.get(c) else r.get(c) for c in cols])
    name = f"exchange-{st.tab}-{s or 'none'}-{e or 'none'}.csv"
    return Response(buf.getvalue(), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{name}"'})

def _saved_filters() -> list[dict]:
    doc = db.setting('saved_filters', {}) or {}
    return [{'name': k, **v} for k, v in sorted(doc.items(), key=lambda kv: kv[0].lower())]

@router.post('/exchange/filters/save')
def save_filter(request: Request, name: str=Form(...), query: str=Form(''), csrf: str=Form(None)):
    user = auth.require_admin(request)
    auth.check_csrf(request, csrf)
    query = xd.Filters.from_query(QueryParams(query)).query()
    name = ' '.join(name.split())[:60]
    if not name:
        flash(request, 'Give the saved filter a name.', 'bad')
        return RedirectResponse('/exchange?' + query + '&filters=1', status_code=303)
    from bond_intel.db.jsonb import dumps
    db.execute("INSERT INTO cfg.setting (key, value, updated_by) VALUES ('saved_filters', jsonb_build_object(CAST(:n AS text), CAST(:v AS jsonb)), :u) ON CONFLICT (key) DO UPDATE SET value = cfg.setting.value || jsonb_build_object(CAST(:n AS text), CAST(:v AS jsonb)), updated_by = :u", actor=user.email, n=name, v=dumps({'query': query, 'by': user.email, 'at': fmt.now_iso()}), u=user.email)
    flash(request, f'Saved the filter “{name}”. Everyone can use it.')
    return RedirectResponse('/exchange?' + query, status_code=303)

@router.post('/exchange/filters/delete')
def delete_filter(request: Request, name: str=Form(...), csrf: str=Form(None)):
    user = auth.require_admin(request)
    auth.check_csrf(request, csrf)
    db.execute("UPDATE cfg.setting SET value = value - CAST(:n AS text), updated_by = :u WHERE key = 'saved_filters'", actor=user.email, n=name, u=user.email)
    flash(request, f'Deleted the saved filter “{name}”.')
    return RedirectResponse('/exchange?filters=1', status_code=303)
