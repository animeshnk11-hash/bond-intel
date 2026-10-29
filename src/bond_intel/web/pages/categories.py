from __future__ import annotations
from collections import Counter, defaultdict
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from bond_intel.reference.categories import Categories
from bond_intel.web import auth, charts, db
from bond_intel.web.app import LAYOUT_Q, page
from bond_intel.web.logos import logos
router = APIRouter()
UNCLASSIFIED = 'Not yet classified'
LISTINGS_SQL = "\nSELECT t.task_key, t.name AS platform, t.status, l.snap_date, l.isin, l.issuer, i.issuer_name AS nsdl_issuer,\n       i.category AS nsdl_category\n  FROM ops.task t\n  JOIN LATERAL (SELECT max(x.snap_date) AS d FROM obpp.listing_daily x WHERE x.source_key = t.task_key) m ON true\n  JOIN obpp.listing_daily l ON l.source_key = t.task_key AND l.snap_date = m.d\n  LEFT JOIN ref.instrument i ON i.isin = l.isin::bpchar\n WHERE t.kind = 'obpp_site' AND t.status IN ('live', 'paused')\n"

def load() -> dict | None:
    rows = db.rows(LISTINGS_SQL)
    if not rows:
        return None
    cats = Categories.from_setting(db.setting('bond_categories'))
    by_site = Counter((r['task_key'] for r in rows))
    counts: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        r['category'] = cats.of(r['isin'], r['issuer'], r['nsdl_issuer'], r['nsdl_category']) or UNCLASSIFIED
        counts[r['category']][r['task_key']] += 1
    return {'rows': rows, 'cats': cats, 'by_site': by_site, 'counts': counts, 'sites': {r['task_key']: r for r in rows}, 'keys': sorted(by_site, key=lambda k: (-by_site[k], k)), 'last': max((r['snap_date'] for r in rows))}

@router.get('/categories', response_class=HTMLResponse)
def categories(request: Request):
    user = auth.require_user(request)
    db.warm(('rows', LISTINGS_SQL, {}), db.SETTINGS_Q, LAYOUT_Q)
    data = load()
    if data is None:
        return page(request, 'categories.html', 'categories', user, heat=None)
    rows, cats, by_site, counts, sites, keys, last = (data[k] for k in ('rows', 'cats', 'by_site', 'counts', 'sites', 'keys', 'last'))

    def note(k: str) -> str | None:
        s = sites[k]
        return f"{s['status']} · {s['snap_date']:%d %b}" if s['snap_date'] < last else None
    logo = logos()
    cols = [{'key': k, 'label': sites[k]['platform'], 'logo': logo.get(k), 'note': note(k)} for k in keys]

    def only_on(c: Counter) -> str | None:
        on = [k for k in keys if c[k]]
        return f"Only on {sites[on[0]]['platform']}" if len(on) == 1 else None
    group_order = list(dict.fromkeys((cats.group[c] for c in cats.order)))
    grouped: dict[str, list[str]] = defaultdict(list)
    for cat in counts:
        grouped[cats.group.get(cat, UNCLASSIFIED)].append(cat)
    groups = []
    for g in sorted(grouped, key=lambda g: group_order.index(g) if g in group_order else len(group_order)):
        members = sorted(grouped[g], key=lambda c: (-sum(counts[c].values()), c))
        groups.append({'label': g, 'chip': None if g == UNCLASSIFIED else only_on(sum((counts[c] for c in members), Counter())), 'rows': [{'label': 'New issuers' if c == UNCLASSIFIED else c, 'counts': [counts[c][k] for k in keys], 'chip': None if c == UNCLASSIFIED else only_on(counts[c])} for c in members]})
    heat = charts.share_heat(cols, groups, {'label': 'All categories', 'counts': [by_site[k] for k in keys]})
    classified = [c for c in counts if c != UNCLASSIFIED]
    only = sum((1 for c in classified if sum((1 for k in keys if counts[c][k])) == 1))
    return page(request, 'categories.html', 'categories', user, heat=heat, last=last, platforms=len(keys), groups=len([g for g in groups if g['label'] != UNCLASSIFIED]), categories=len(classified), overlapping=len(classified) - only, only=only, listings=len(rows), isins=len({r['isin'] for r in rows}), unclassified=sum(counts[UNCLASSIFIED].values()), ramp=list(reversed(charts.RAMP)), pending=[] if auth.public_view() else cats.pending(rows))
