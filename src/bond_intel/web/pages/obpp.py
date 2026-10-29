from __future__ import annotations
import csv
import io
import statistics
from collections import Counter
from datetime import date
from urllib.parse import urlencode
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from bond_intel.reference.taxonomy import COUPON_FREQS
from bond_intel.web import auth, db, fmt
from bond_intel.web import exchange_data as xd
from bond_intel.web.app import page
router = APIRouter()
TABS = {'listings': 'Listings', 'changes': 'Changes'}
SORTS = {'platforms': 'Platforms, then best YTM', 'ytm': 'Best YTM', 'gap': 'YTM gap', 'min': 'Min. investment', 'maturity': 'Maturity', 'bond': 'Bond'}
GROUPS = {'none': 'None', 'bucket': 'Rating bucket', 'freq': 'Coupon frequency', 'year': 'Maturity year', 'issuer': 'Issuer'}
LISTS = ('plat', 'bucket', 'freq', 'yrs')
PAGE_SIZES = (10, 25, 50)
COMPARE_SQL = "\nSELECT l.isin, t.task_key, t.name AS platform, l.ytm_pct, l.clean_price_100, l.dirty_price_100, l.units_available,\n       l.pct_sold, l.min_investment_inr, l.price_per_unit_inr, l.status, l.first_seen_on, l.snap_date\n  FROM ops.task t\n  JOIN LATERAL (SELECT max(x.snap_date) AS d FROM obpp.listing_daily x\n                 WHERE x.source_key = t.task_key AND x.snap_date <= :d) m ON true\n  JOIN obpp.listing_daily l ON l.source_key = t.task_key AND l.snap_date = m.d\n WHERE t.kind = 'obpp_site' AND t.status IN ('live', 'paused') AND l.isin = ANY(:isins)\n ORDER BY l.isin, l.ytm_pct DESC NULLS LAST, t.name\n"
DAYS_SQL = 'SELECT DISTINCT snap_date FROM obpp.listing_daily ORDER BY 1 DESC LIMIT 90'
OFFER_SQL = 'SELECT * FROM obpp.bond_offer(:d)'
CHANGES_SQL = '\nSELECT c.*, mkt.is_sovereign(c.isin) AS sovereign, coalesce(l.rating_code, p.rating_code) AS rating_code,\n       coalesce(l.coupon_freq, p.coupon_freq) AS coupon_freq, coalesce(l.maturity_date, p.maturity_date) AS maturity_date\n  FROM obpp.listing_changes(:d) c\n  LEFT JOIN obpp.listing_daily l ON l.source_key = c.source_key AND l.snap_date = c.snap_date AND l.isin = c.isin\n  LEFT JOIN obpp.listing_daily p ON p.source_key = c.source_key AND p.snap_date = c.prev_date AND p.isin = c.isin\n ORDER BY c.platform, c.issuer, c.isin\n'
COMPARED_SQL = "\nSELECT p.name, obpp.relearned_between(\n           p.task_key,\n           (SELECT x.job_id FROM obpp.listing_daily x WHERE x.source_key = p.task_key AND x.snap_date = p.prev_d LIMIT 1),\n           p.prev_d,\n           (SELECT x.job_id FROM obpp.listing_daily x WHERE x.source_key = p.task_key AND x.snap_date = :d LIMIT 1),\n           :d) AS relearned\n  FROM (SELECT t.task_key, t.name,\n               (SELECT max(x.snap_date) FROM obpp.listing_daily x\n                 WHERE x.source_key = t.task_key AND x.snap_date < :d) AS prev_d\n          FROM ops.task t\n         WHERE t.kind = 'obpp_site' AND t.status IN ('live', 'paused')\n           AND EXISTS (SELECT 1 FROM obpp.listing_daily x WHERE x.source_key = t.task_key AND x.snap_date = :d)) p\n WHERE p.prev_d IS NOT NULL\n"
PLATFORMS_SQL = "SELECT task_key, name, status, coalesce((state->>'partial')::boolean, false) AS partial FROM ops.task WHERE kind = 'obpp_site' AND status IN ('live', 'paused') ORDER BY name"
RUN_AT_SQL = "SELECT max(finished_at) AS at FROM ops.job WHERE job_type = 'obpp.scrape' AND status = 'ok' AND (result->'snapshot'->>'date')::date = :d"

class OState:

    def __init__(self, request: Request):
        q = request.query_params
        self.days: list[date] = [r['snap_date'] for r in db.rows(DAYS_SQL)]
        try:
            asked = date.fromisoformat(q.get('d')) if q.get('d') else None
        except ValueError:
            asked = None
        self.day = asked if asked in self.days else self.days[0] if self.days else None
        self.tab = q.get('tab') if q.get('tab') in TABS else 'listings'
        self.sort = q.get('sort') if q.get('sort') in SORTS else 'platforms'
        self.desc = q.get('dir', 'desc') != 'asc'
        self.group = q.get('group') if q.get('group') in GROUPS else 'none'
        self.n = int(q.get('n')) if q.get('n', '').isdigit() and int(q.get('n')) in PAGE_SIZES else 10
        self.page = max(1, int(q.get('page'))) if q.get('page', '').isdigit() else 1
        self.open = (q.get('open') or '').strip().upper()[:12]
        self.gshow = q.get('gshow') or ''
        self.gov = q.get('gov') == '1'
        self.lists = {k: [v for v in q.getlist(k) if v] for k in LISTS}

    def filters(self, **over) -> list[tuple[str, str]]:
        p = []
        d = over.get('d', self.day if self.day != (self.days[0] if self.days else None) else None)
        if d:
            p.append(('d', str(d)))
        if over.get('gov', self.gov):
            p.append(('gov', '1'))
        for k in LISTS:
            p += [(k, v) for v in over.get(k, self.lists[k])]
        return p

    def active(self) -> int:
        return sum((1 for k in LISTS if self.lists[k])) + (1 if self.gov else 0)

    def link(self, **kw) -> str:
        base = {'tab': self.tab, 'sort': self.sort, 'dir': 'desc' if self.desc else 'asc', 'group': self.group, 'n': self.n}
        base.update(kw)
        defaults = {'tab': 'listings', 'sort': 'platforms', 'dir': 'desc', 'group': 'none', 'n': 10, 'page': 1}
        extra = [(k, str(v)) for k, v in base.items() if v not in (None, '') and defaults.get(k) != v]
        return '/obpp?' + urlencode(self.filters() + extra)

def _scale() -> dict:
    return (db.setting('ratings', {}) or {}).get('scale') or {}

def _decorate(rows: list[dict], scale: dict, day: date) -> list[dict]:
    for r in rows:
        r['label'] = fmt.bond_label(r.get('issuer') or r.get('bond_name'), r.get('coupon_pct'), r.get('maturity_date'), 30, month=True)
        r['bucket'] = 'SOVEREIGN' if r.get('sovereign') else (scale.get(r.get('rating_code') or '', {}) or {}).get('bucket', 'BELOW_BBB')
        m = r.get('maturity_date')
        r['years'] = (m - day).days / 365.25 if m else None
    return rows

def _apply(rows: list[dict], st: OState, skip: str | None=None) -> list[dict]:
    L = st.lists
    out = []
    for r in rows:
        if not st.gov and r.get('sovereign'):
            continue
        if skip != 'plat' and L['plat'] and (not set(L['plat']) & set(r.get('listed_on') or [])):
            continue
        if skip != 'bucket' and L['bucket'] and (r['bucket'] not in L['bucket']):
            continue
        if skip != 'freq' and L['freq'] and ((r.get('coupon_freq') or '') not in L['freq']):
            continue
        if skip != 'yrs' and L['yrs']:
            y = r['years']
            if y is None or not any((lo <= y < hi for k, _, lo, hi in xd.YEARS if k in L['yrs'])):
                continue
        out.append(r)
    return out

def _facets(rows: list[dict], st: OState) -> dict[str, Counter]:
    out: dict[str, Counter] = {}
    for key in LISTS:
        c: Counter = Counter()
        for r in _apply(rows, st, skip=key):
            if key == 'plat':
                c.update(r.get('listed_on') or [])
            elif key == 'bucket':
                c[r['bucket']] += 1
            elif key == 'freq':
                c[r.get('coupon_freq') or ''] += 1
            elif key == 'yrs' and r['years'] is not None:
                for k, _, lo, hi in xd.YEARS:
                    if lo <= r['years'] < hi:
                        c[k] += 1
        out[key] = c
    return out

def _sort(rows: list[dict], key: str, desc: bool) -> list[dict]:

    def val(r):
        if key == 'platforms':
            return (r['platforms'], float(r['best_ytm']) if r['best_ytm'] is not None else -1)
        if key == 'ytm':
            return float(r['best_ytm']) if r['best_ytm'] is not None else None
        if key == 'gap':
            return float(r['ytm_gap_pct']) if r['ytm_gap_pct'] is not None else None
        if key == 'min':
            return float(r['min_investment_inr']) if r['min_investment_inr'] is not None else None
        if key == 'maturity':
            return r['maturity_date']
        return r['label'].lower()
    have = [r for r in rows if val(r) is not None]
    none = [r for r in rows if val(r) is None]
    return sorted(have, key=val, reverse=desc) + none

def _group_key(r: dict, by: str) -> str:
    if by == 'bucket':
        return r['bucket']
    if by == 'freq':
        return fmt.freq(r.get('coupon_freq')).capitalize() if r.get('coupon_freq') else 'Unknown'
    if by == 'year':
        return str(r['maturity_date'].year) if r.get('maturity_date') else 'Unknown'
    if by == 'issuer':
        return fmt.short_issuer(r.get('issuer'), 40) or 'Unknown'
    return ''

def _listings(st: OState, rows: list[dict]) -> dict:
    ranked = _sort(rows, st.sort, st.desc)
    if st.group == 'none':
        pages = max(1, -(-len(ranked) // st.n))
        pg = min(st.page, pages)
        groups = [{'key': '', 'label': '', 'rows': ranked[(pg - 1) * st.n:pg * st.n], 'count': len(ranked)}]
    else:
        pages, pg = (1, 1)
        labels = dict(xd.buckets())
        acc: dict[str, dict] = {}
        for r in ranked:
            k = _group_key(r, st.group)
            acc.setdefault(k, {'key': k, 'label': labels.get(k, k) if st.group == 'bucket' else k, 'rows': []})
            acc[k]['rows'].append(r)
        order = [k for k, _ in xd.buckets()] if st.group == 'bucket' else None
        groups = sorted(acc.values(), key=lambda g: (order.index(g['key']) if order and g['key'] in order else 99, g['key'] if st.group == 'year' else -len(g['rows'])))
        for g in groups:
            g['count'] = len(g['rows'])
            g['all'] = g['key'] == st.gshow
            if not g['all']:
                g['rows'] = g['rows'][:5]
    shown = [r for g in groups for r in g['rows']]
    cmp: dict[str, list[dict]] = {}
    if shown:
        for c in db.rows(COMPARE_SQL, d=st.day, isins=[r['isin'] for r in shown]):
            cmp.setdefault(c['isin'], []).append(c)
    for r in shown:
        r['compare'] = cmp.get(r['isin'], [])
        best = r['best_ytm']
        for c in r['compare']:
            c['best'] = best is not None and c['ytm_pct'] == best and (c['status'] in ('live', 'unknown'))
    return {'groups': groups, 'pages': pages, 'pg': pg, 'total': len(ranked)}
CHANGE_KINDS = [('new', 'New listings'), ('removed', 'Removed'), ('sold_out', 'Sold out'), ('back_on_sale', 'Back on sale')]

def _change_rows(st: OState, offer: list[dict], scale: dict) -> list[dict]:
    rows = _decorate(db.rows(CHANGES_SQL, d=st.day), scale, st.day)
    on_offer = {r['isin']: r for r in offer}
    for r in rows:
        o = on_offer.get(r['isin'])
        if o is not None:
            r.update(sovereign=o['sovereign'], bucket=o['bucket'], coupon_freq=o.get('coupon_freq'), years=o['years'])
        r['listed_on'] = [r['platform']]
    return _apply(rows, st)

def _changes(st: OState, offer: list[dict], scale: dict) -> dict:
    rows = _change_rows(st, offer, scale)
    sites = [s for s in db.rows(COMPARED_SQL, d=st.day) if not st.lists['plat'] or s['name'] in st.lists['plat']]
    for r in rows:
        r['label'] = fmt.bond_label(r.get('issuer') or r.get('bond_name'), None, None, 34)
    sections = [{'key': k, 'title': t, 'rows': [r for r in rows if r['change'] == k]} for k, t in CHANGE_KINDS]
    sold = [r for r in rows if r['units_sold']]
    sold.sort(key=lambda r: -float(r['inr_sold'] or 0))
    moves = [r for r in rows if r['change'] is None and r['ytm_delta'] is not None and (abs(float(r['ytm_delta'])) >= 0.05)]
    moves.sort(key=lambda r: -abs(float(r['ytm_delta'])))
    relearned = sorted((s['name'] for s in sites if s['relearned']))
    return {'sections': sections, 'sold': sold[:25], 'moves': moves[:25], 'compared': len(sites), 'relearned': relearned, 'total': len(rows), 'units': sum((int(r['units_sold'] or 0) for r in sold)), 'inr': sum((float(r['inr_sold'] or 0) for r in sold))}

def _platforms() -> list[dict]:
    return db.rows(PLATFORMS_SQL)

@router.get('/obpp', response_class=HTMLResponse)
def obpp(request: Request):
    user = auth.require_user(request)
    from bond_intel.web.app import LAYOUT_Q
    db.warm(('rows', DAYS_SQL, {}), LAYOUT_Q, db.SETTINGS_Q, ('rows', PLATFORMS_SQL, {}))
    st = OState(request)
    if st.day is not None:
        db.warm(('rows', OFFER_SQL, {'d': st.day}), ('rows', RUN_AT_SQL, {'d': st.day}), *([('rows', CHANGES_SQL, {'d': st.day}), ('rows', COMPARED_SQL, {'d': st.day})] if st.tab == 'changes' else []))
    ctx: dict = {'st': st, 'tabs': TABS, 'sorts': SORTS, 'groups_opts': GROUPS, 'page_sizes': PAGE_SIZES, 'open_filters': request.query_params.get('filters') == '1', 'query': request.url.query}
    if st.day is None:
        return page(request, 'obpp.html', 'obpp', user, **ctx)
    scale = _scale()
    all_rows = _decorate(db.rows(OFFER_SQL, d=st.day), scale, st.day)
    rows = _apply(all_rows, st)
    sites = _platforms()
    per = Counter((p for r in rows for p in r.get('listed_on') or []))
    ytms = [float(r['best_ytm']) for r in rows if r['best_ytm'] is not None]
    ctx.update(rows=rows, sites=sites, per_platform=[(s['name'], per.get(s['name'], 0), s['partial']) for s in sites], listings=sum((r['platforms'] for r in rows)), multi=sum((1 for r in rows if r['platforms'] > 1)), median=statistics.median(ytms) if ytms else None, facets=_facets(all_rows, st), opts={'plat': [(s['name'], s['name']) for s in sites], 'bucket': [(k, lbl if k in ('BELOW_BBB', 'SOVEREIGN') else k) for k, lbl in xd.buckets() if st.gov or k != 'SOVEREIGN'], 'freq': [(k, fmt.freq(k).capitalize()) for k in COUPON_FREQS], 'yrs': [(k, lbl) for k, lbl, _lo, _hi in xd.YEARS]}, runs=db.row(RUN_AT_SQL, d=st.day))
    if st.tab == 'listings':
        ctx['ls'] = _listings(st, rows)
    else:
        ctx['ch'] = _changes(st, all_rows, scale)
    return page(request, 'obpp.html', 'obpp', user, **ctx)

@router.get('/obpp/download.csv')
def obpp_download(request: Request):
    auth.require_user(request)
    st = OState(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    if st.day is not None and st.tab == 'changes':
        cols = ['platform', 'isin', 'change', 'snap_date', 'prev_date', 'issuer', 'bond_name', 'status', 'prev_status', 'units_sold', 'inr_sold', 'pct_sold_delta', 'ytm_delta', 'price_delta', 'relearned']
        w.writerow(cols)
        scale = _scale()
        offer = _decorate(db.rows(OFFER_SQL, d=st.day), scale, st.day)
        for r in _change_rows(st, offer, scale):
            w.writerow([r[c] for c in cols])
    elif st.day is not None:
        rows = _sort(_apply(_decorate(db.rows(OFFER_SQL, d=st.day), _scale(), st.day), st), st.sort, st.desc)
        cols = ['isin', 'label', 'issuer', 'rating_agency', 'rating_code', 'bucket', 'coupon_pct', 'coupon_freq', 'maturity_date', 'platforms', 'sold_out', 'best_ytm', 'low_ytm', 'ytm_gap_pct', 'min_investment_inr', 'listed_on', 'best_on', 'snap_date']
        w.writerow(cols)
        for r in rows:
            w.writerow([';'.join(r[c] or []) if c in ('listed_on', 'best_on') else r.get(c) for c in cols])
    return Response(buf.getvalue(), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="obpp-{st.tab}-{st.day}.csv"'})
