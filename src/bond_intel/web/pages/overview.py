from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from bond_intel.web import auth, charts, db, fmt, sched
from bond_intel.web import exchange_data as xd
from bond_intel.web.app import page
router = APIRouter()
CARD_WINDOWS = {'D1': 'Day', 'R5': '5 days', 'R22': '22 days'}
CARD_SORTS = ('value', 'trades', 'qty', 'ytm')
CARD_GROUPS = ('none', 'bucket', 'cat', 'issuer', 'market')
TOTALS_SQL = 'SELECT trade_date, value_inr, trades, isins, prev_value_inr, prev_trades, avg5_value_inr FROM mkt.v_market_totals WHERE NOT sovereign AND trade_date <= :d ORDER BY trade_date DESC LIMIT 22'
BY_EXCHANGE_SQL = 'SELECT exchange, count(DISTINCT isin) AS n FROM mkt.v_trade_leg WHERE trade_date = :d AND NOT sovereign GROUP BY exchange'
LOADED_SQL = 'SELECT max(loaded_at) FROM mkt.trade_daily WHERE trade_date = :d'

def _choice(value: str | None, allowed, default: str) -> str:
    return value if value in allowed else default

@router.get('/', response_class=HTMLResponse)
def overview(request: Request):
    user = auth.require_user(request)
    q = request.query_params
    win = _choice(q.get('win'), CARD_WINDOWS, 'D1')
    sort = _choice(q.get('sort'), CARD_SORTS, 'value')
    group = _choice(q.get('group'), CARD_GROUPS, 'none')
    from bond_intel.web.app import LAYOUT_Q
    db.warm(xd.LATEST_Q, LAYOUT_Q, db.SETTINGS_Q, ('rows', sched.NEXT_OF_SQL, {'j': 'report.send'}))
    report_next = sched.next_of('report.send')
    d = xd.latest_day()
    if d is not None:
        db.warm(('rows', TOTALS_SQL, {'d': d}), ('rows', BY_EXCHANGE_SQL, {'d': d}), ('scalar', LOADED_SQL, {'d': d}), xd.agg_q(d, d), xd.window_q(xd.Filters(win=win, asof=d), d))
    if d is None:
        return page(request, 'overview.html', 'overview', user, d=None, report_next=report_next)
    days = db.rows(TOTALS_SQL, d=d)[::-1]
    cur = next((x for x in days if x['trade_date'] == d), None) or {'trade_date': d}
    prev_day = days[-2]['trade_date'] if len(days) > 1 and cur is days[-1] else None
    by_exchange = {r['exchange']: r['n'] for r in db.rows(BY_EXCHANGE_SQL, d=d)}
    both = max(0, sum(by_exchange.values()) - int(cur['isins'])) if cur.get('isins') is not None else 0
    loaded_at = db.scalar(LOADED_SQL, d=d)
    day_rows = xd.apply(xd.aggregate(d, d), xd.Filters(), d)
    most = max(day_rows, key=lambda r: float(r['value_inr'] or 0), default=None)
    buckets = [(k, lbl) for k, lbl in xd.buckets() if k != 'SOVEREIGN']
    total = sum((float(r['value_inr'] or 0) for r in day_rows)) or 1.0
    per = {k: sum((float(r['value_inr'] or 0) for r in day_rows if r['bucket'] == k)) for k, _ in buckets}
    money = charts.meters([{'label': short_bucket(k, lbl), 'value': per[k], 'share': per[k] / total, 'note': f'{per[k] / total * 100:.0f}%'} for k, lbl in buckets], fmt=lambda v: fmt.cr(v, 1))
    vals = [float(x['value_inr'] or 0) / 10000000.0 for x in days]
    n = len(days)
    ticks = [f"{x['trade_date'].day}" if (n - 1 - i) % 3 == 0 else '' for i, x in enumerate(days)]
    tips = [charts.tip(fmt.dow(x['trade_date']), [('Value traded', charts.SERIES[0], fmt.cr(x['value_inr'], 1))], f"{fmt.num(x['trades'])} trades · {fmt.num(x['isins'])} bonds") for x in days]
    chart = charts.columns([fmt.dshort(x['trade_date']) for x in days], [{'name': 'Value traded', 'values': vals, 'color': charts.SERIES[0]}], height=200, fmt=lambda v: f'Rs {v:,.1f} cr', tick_labels=ticks, tips=tips, emphasis=n - 1, aria='Corporate value traded per day, last 22 trading days')
    peak = max(days, key=lambda x: float(x['value_inr'] or 0)) if days else None
    avg5 = cur.get('avg5_value_inr')
    w = xd.window(xd.Filters(win=win, asof=d)) or (d, d)
    card_rows = day_rows if w == (d, d) else xd.apply(xd.aggregate(*w), xd.Filters(), d)
    ranked = xd.sort_rows(card_rows, sort)
    labels = dict(xd.buckets())
    all_groups = 0
    if group == 'none':
        groups = [{'key': '', 'label': '', 'rows': ranked[:5], 'value': None, 'trades': None}]
    else:
        groups = xd.group_rows(ranked, group, labels)
        all_groups = len(groups)
        if group != 'bucket':
            groups = groups[:4]
        for g in groups:
            g['count'] = len(g['rows'])
            g['rows'] = g['rows'][:3]
    vmax = max((float(r['value_inr'] or 0) for g in groups for r in g['rows']), default=1) or 1
    guard = xd.guard()
    best = []
    for k, lbl in buckets:
        cands = [r for r in day_rows if r['bucket'] == k and r['ytm_pct'] is not None and (0 < float(r['ytm_pct']) < 50) and xd.passes_guard(r, guard)]
        if cands:
            best.append((short_bucket(k, lbl), max(cands, key=lambda r: float(r['ytm_pct']))))
    return page(request, 'overview.html', 'overview', user, d=d, cur=cur, prev_day=prev_day, loaded_at=loaded_at, by_exchange=by_exchange, both=both, most=most, money=money, chart=chart, days=days, peak=peak, avg5=avg5, win=win, sort=sort, group=group, groups=groups, all_groups=all_groups, vmax=vmax, card_count=len(card_rows), windows=CARD_WINDOWS, sorts={k: xd.SORTS[k][0] for k in CARD_SORTS}, group_opts={k: xd.GROUPS[k] for k in CARD_GROUPS}, best=best, guard_text=xd.guard_text(guard), report_next=report_next, window=w)

def short_bucket(key: str, label: str) -> str:
    return label if key == 'BELOW_BBB' else key
