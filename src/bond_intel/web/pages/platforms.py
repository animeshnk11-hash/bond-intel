from __future__ import annotations
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from bond_intel.web import auth, charts, db, fmt
from bond_intel.web import exchange_data as xd
from bond_intel.web.app import page
router = APIRouter()
PERIODS = {7: '7 days', 30: '30 days', 90: '90 days'}
BUCKET_COLORS = {'AAA': charts.ORDINAL[0], 'AA': charts.ORDINAL[1], 'A': charts.ORDINAL[2], 'BBB': charts.ORDINAL[3], 'BELOW_BBB': charts.ORDINAL[4], 'SOVEREIGN': '#9AA0B4'}
LATEST_SQL = "\nSELECT t.task_key, t.name AS platform, l.isin, l.issuer, l.rating_code, l.ytm_pct, l.min_investment_inr,\n       l.maturity_date, l.coupon_pct, l.status, l.first_seen_on, l.units_available, l.pct_sold,\n       l.status IN ('live', 'unknown') AS buyable, mkt.is_sovereign(l.isin) AS sovereign,\n       i.rating_code AS nsdl_code, coalesce(i.category, l.category) AS category\n  FROM ops.task t\n  JOIN LATERAL (SELECT max(x.snap_date) AS d FROM obpp.listing_daily x\n                 WHERE x.source_key = t.task_key AND x.snap_date <= :t) m ON true\n  JOIN obpp.listing_daily l ON l.source_key = t.task_key AND l.snap_date = m.d\n  LEFT JOIN ref.instrument i ON i.isin = l.isin::bpchar\n WHERE t.kind = 'obpp_site' AND t.status IN ('live', 'paused')\n"
MOVES_SQL = "\nWITH s AS (\n    SELECT l.source_key, l.isin, l.snap_date, l.job_id, l.units_available, l.pct_sold, l.status, l.first_seen_on,\n           l.issuer, l.coupon_pct, l.maturity_date,\n           lag(l.units_available) OVER w AS prev_units, lag(l.pct_sold) OVER w AS prev_pct,\n           lag(l.status) OVER w AS prev_status, lag(l.snap_date) OVER w AS prev_date, lag(l.job_id) OVER w AS prev_job\n      FROM obpp.listing_daily l\n     WHERE l.source_key = :k AND l.snap_date BETWEEN :f - 1 AND :t\n    WINDOW w AS (PARTITION BY l.isin ORDER BY l.snap_date)),\npairs AS MATERIALIZED (   -- once per pair of snapshot runs, not per bond\n    SELECT p.*, obpp.relearned_between(:k, p.prev_job, p.prev_date, p.job_id, p.snap_date) AS relearned\n      FROM (SELECT DISTINCT s.prev_job, s.prev_date, s.job_id, s.snap_date FROM s\n             WHERE s.snap_date >= :f AND s.prev_date IS NOT NULL) p),\nm AS (\n    SELECT s.*, s.prev_date IS NOT NULL AND NOT coalesce(p.relearned, false) AS compared\n      FROM s LEFT JOIN pairs p ON p.snap_date = s.snap_date AND p.prev_date = s.prev_date\n                              AND p.job_id IS NOT DISTINCT FROM s.job_id AND p.prev_job IS NOT DISTINCT FROM s.prev_job\n     WHERE s.snap_date >= :f)\nSELECT isin, max(issuer) AS issuer, max(coupon_pct) AS coupon_pct, max(maturity_date) AS maturity_date,\n       sum(CASE WHEN compared AND snap_date - prev_date = 1 AND prev_units > units_available\n                THEN prev_units - units_available END) AS units_sold,\n       sum(CASE WHEN compared AND snap_date - prev_date = 1 AND pct_sold > prev_pct THEN pct_sold - prev_pct END)\n           AS pct_up,\n       min(snap_date) FILTER (WHERE compared AND status = 'sold_out' AND prev_status IS DISTINCT FROM 'sold_out')\n           AS sold_out_on,\n       min(first_seen_on) AS first_seen_on\n  FROM m GROUP BY isin\n"
LAST_SQL = 'SELECT max(snap_date) FROM obpp.listing_daily'
FIRST_SQL = 'SELECT min(snap_date) FROM obpp.listing_daily'
BENCH_SQL = 'SELECT * FROM obpp.platform_benchmark(:f, :t)'
PAIR_DAYS_SQL = 'SELECT count(DISTINCT snap_date) FROM obpp.listing_daily WHERE snap_date BETWEEN :f AND :t AND snap_date - 1 IN (SELECT snap_date FROM obpp.listing_daily)'

def _bands(v: float | None, edges: list[float], labels: list[str]) -> str | None:
    if v is None:
        return None
    for edge, label in zip(edges, labels, strict=False):
        if v < edge:
            return label
    return labels[-1]
TENURE = ([1, 3, 5, 10], ['Under 1 yr', '1–3 yrs', '3–5 yrs', '5–10 yrs', '10+ yrs'])
RATE = ([9, 10, 11, 12], ['Under 9%', '9–10%', '10–11%', '11–12%', '12%+'])
TICKET = ([1000, 10000, 100000], ['Under Rs 1,000', 'Rs 1,000–10,000', 'Rs 10,000–1 lakh', 'Rs 1 lakh+'])

def _bucket(r: dict, scale: dict) -> str:
    if r['sovereign']:
        return 'SOVEREIGN'
    code = r.get('nsdl_code') or r.get('rating_code') or ''
    return (scale.get(code) or {}).get('bucket', 'BELOW_BBB')

def load(period: int, last: date) -> dict:
    to, frm = (last, last - timedelta(days=period - 1))
    db.warm(('rows', BENCH_SQL, {'f': frm, 't': to}), ('rows', LATEST_SQL, {'t': to}), ('scalar', PAIR_DAYS_SQL, {'f': frm, 't': to}))
    bench = db.rows(BENCH_SQL, f=frm, t=to)
    scale = (db.setting('ratings', {}) or {}).get('scale') or {}
    rows = db.rows(LATEST_SQL, t=to)
    for r in rows:
        r['bucket'] = _bucket(r, scale)
    by_site: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_site[r['platform']].append(r)
    sets = {n: {r['isin'] for r in ls} for n, ls in by_site.items()}
    return {'frm': frm, 'to': to, 'bench': bench, 'scale': scale, 'rows': rows, 'by_site': by_site, 'sets': sets}

@router.get('/platforms', response_class=HTMLResponse)
def platforms(request: Request):
    user = auth.require_user(request)
    q = request.query_params
    period = int(q.get('p')) if q.get('p', '').isdigit() and int(q.get('p')) in PERIODS else 7
    from bond_intel.web.app import LAYOUT_Q
    db.warm(('scalar', LAST_SQL, {}), ('scalar', FIRST_SQL, {}), LAYOUT_Q, db.SETTINGS_Q)
    last = db.scalar(LAST_SQL)
    ctx: dict = {'periods': PERIODS, 'period': period, 'last': last}
    if last is None:
        return page(request, 'platforms.html', 'platforms', user, **ctx)
    data = load(period, last)
    frm, to, bench, scale, rows, by_site = (data[k] for k in ('frm', 'to', 'bench', 'scale', 'rows', 'by_site'))
    names = [b['platform'] for b in sorted(bench, key=lambda b: -b['bonds_live'])]
    first_day = db.scalar(FIRST_SQL)
    pair_days = db.scalar(PAIR_DAYS_SQL, f=frm, t=to) or 0
    keys = [(k, lbl if k in ('BELOW_BBB', 'SOVEREIGN') else k, BUCKET_COLORS.get(k, charts.MUTED)) for k, lbl in xd.buckets() if any((r['bucket'] == k for r in rows))]
    order = [k for k, _, _ in keys]
    keys.sort(key=lambda x: (x[0] == 'SOVEREIGN', order.index(x[0])))
    mix = charts.stack100([{'label': n, 'parts': Counter((r['bucket'] for r in by_site[n]))} for n in names], keys, fmt=lambda v: f'{v:,.0f}')
    mix_legend = charts.legend([(name, color) for _, name, color in keys])
    sets = {n: data['sets'].get(n, set()) for n in names}
    matrix = [[len(sets[a] & sets[b]) if a != b else None for b in names] for a in names]
    heat = charts.heat(names, names, matrix, title='bonds both list')
    per_isin: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r['buyable'] and r['ytm_pct'] is not None and (not r['sovereign']):
            per_isin[r['isin']].append(r)
    gaps = []
    for isin, ls in per_isin.items():
        if len(ls) < 2:
            continue
        ys = [float(x['ytm_pct']) for x in ls]
        gaps.append({'isin': isin, 'gap': max(ys) - min(ys), 'label': fmt.bond_label(ls[0]['issuer'], ls[0]['coupon_pct'], ls[0]['maturity_date'], 18, True), 'points': sorted(((x['platform'], float(x['ytm_pct'])) for x in ls), key=lambda p: p[1])})
    gaps.sort(key=lambda g: -g['gap'])
    ranges = charts.ranges(gaps[:12]) if gaps else ''
    shared_n = len([g for g in gaps if g['gap'] > 0])
    site = q.get('site')
    drawer = _drawer(site, bench, by_site, sets, rows, frm, to, scale) if site else None
    ctx.update(bench=bench, frm=frm, to=to, mix=mix, mix_legend=mix_legend, heat=heat, ranges=ranges, gaps=gaps[:12], shared_n=shared_n, first_day=first_day, pair_days=pair_days, drawer=drawer, names=names)
    return page(request, 'platforms.html', 'platforms', user, **ctx)

def _drawer(key: str, bench: list[dict], by_site: dict, sets: dict, rows: list[dict], frm: date, to: date, scale: dict) -> dict | None:
    p = profile(key, bench, by_site, sets, rows, frm, to)
    if p is None:
        return None
    n = p['listed'] or 1

    def meters(parts: list[tuple[str, int]]) -> str:
        return charts.meters([{'label': k, 'value': v, 'share': v / n, 'note': f'{v / n * 100:.0f}%'} for k, v in parts], fmt=lambda v: f'{v:,.0f}')
    mine = len(sets.get(p['name'], set())) or 1
    overlap = charts.meters([{'label': o['platform'], 'value': o['shared'], 'share': o['shared'] / mine, 'note': f"{o['shared'] / mine * 100:.0f}% of {p['name']}'s"} for o in p['overlap']], fmt=lambda v: f'{v:,.0f} shared')
    return {**p, 'mix': {title: meters(parts) for title, parts in p['mix'].items()}, 'overlap': overlap, 'exclusive': p['exclusive'][:10]}

def profile(key: str, bench: list[dict], by_site: dict, sets: dict, rows: list[dict], frm: date, to: date) -> dict | None:
    b = next((x for x in bench if x['source_key'] == key), None)
    if b is None:
        return None
    name = b['platform']
    mine = by_site.get(name, [])
    task = db.row("SELECT config->>'list_url' AS url, state FROM ops.task WHERE task_key = :k", k=key) or {}

    def parts(counter: Counter, order: list[str]) -> list[tuple[str, int]]:
        return [(k, counter[k]) for k in order if counter.get(k)]
    labels = dict(xd.buckets())
    rating = Counter((labels.get(r['bucket'], r['bucket']) if r['bucket'] in ('BELOW_BBB', 'SOVEREIGN') else r['bucket'] for r in mine))
    cats = Counter((r.get('category') or 'Not known' for r in mine))
    tenure = Counter((_bands((r['maturity_date'] - to).days / 365.25 if r['maturity_date'] else None, *TENURE) or 'Not known' for r in mine))
    coupon = Counter((_bands(float(r['coupon_pct']) if r['coupon_pct'] is not None else None, *RATE) or 'Not known' for r in mine))
    ytm = Counter((_bands(float(r['ytm_pct']) if r['ytm_pct'] is not None else None, *RATE) or 'Not known' for r in mine))
    ticket = Counter((_bands(float(r['min_investment_inr']) if r['min_investment_inr'] is not None else None, *TICKET) or 'Not known' for r in mine))
    rating_order = [lbl if k in ('BELOW_BBB', 'SOVEREIGN') else k for k, lbl in xd.buckets()]
    mix = {'Rating': parts(rating, rating_order), 'Issuer type': parts(cats, [k for k, _ in cats.most_common()]), 'Years to maturity': parts(tenure, TENURE[1] + ['Not known']), 'Coupon': parts(coupon, RATE[1] + ['Not known']), 'Yield (YTM)': parts(ytm, RATE[1] + ['Not known']), 'Minimum investment': parts(ticket, TICKET[1] + ['Not known'])}
    moves = db.rows(MOVES_SQL, k=key, f=frm, t=to)
    for m in moves:
        m['label'] = fmt.bond_label(m['issuer'], m['coupon_pct'], m['maturity_date'], 26, True)
        m['days_to_sell'] = (m['sold_out_on'] - m['first_seen_on']).days if m['sold_out_on'] and m['first_seen_on'] else None
    fast = sorted([m for m in moves if m['units_sold'] or m['pct_up']], key=lambda m: (-float(m['units_sold'] or 0), -float(m['pct_up'] or 0)))[:10]
    sold_out = [m for m in moves if m['sold_out_on']]
    others = {x: s for x, s in sets.items() if x != name}
    my = sets.get(name, set())
    overlap = [{'platform': x, 'shared': len(my & s)} for x, s in sorted(others.items(), key=lambda kv: -len(my & kv[1])) if my & s]
    exclusive = sorted([r for r in mine if not any((r['isin'] in s for s in others.values()))], key=lambda r: -(float(r['ytm_pct']) if r['ytm_pct'] is not None else -1))
    for r in exclusive:
        r['label'] = fmt.bond_label(r['issuer'], r['coupon_pct'], r['maturity_date'], 26, True)
    listed = Counter((r['isin'] for r in rows))
    top: dict[str, float] = {}
    for r in rows:
        if r['buyable'] and r['ytm_pct'] is not None:
            top[r['isin']] = max(top.get(r['isin'], float(r['ytm_pct'])), float(r['ytm_pct']))
    priced = [r for r in mine if listed[r['isin']] > 1 and r['buyable'] and (r['ytm_pct'] is not None)]
    behind = [(top[r['isin']] - float(r['ytm_pct'])) * 100 for r in priced if float(r['ytm_pct']) < top[r['isin']]]
    return {'b': b, 'name': name, 'url': task.get('url'), 'state': task.get('state') or {}, 'listed': len(mine), 'mix': mix, 'fast': fast, 'sold_out': sold_out, 'overlap': overlap, 'exclusive': exclusive, 'exclusive_n': len(exclusive), 'best': len(priced) - len(behind), 'priced': len(priced), 'behind': len(behind), 'behind_median': statistics.median(behind) if behind else None}
