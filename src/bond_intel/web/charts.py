from __future__ import annotations
import json
import math
from html import escape
SERIES = ['#5218E8', '#9B7BF5', '#0891B2']
ORDINAL = ['#22085E', '#3F14B0', '#5E2FE6', '#8A68F0', '#B09AF5']
RAMP = ORDINAL + ['#DCD2FB']
MUTED = '#C9CBD6'
GRID = '#E6E7EE'
AXIS_TEXT = '#6B6F80'
FAINT = '#D9CFFB'

def tip(title: str, rows: list[tuple[str, str | None, str]], foot: str | None=None) -> str:
    return escape(json.dumps({'t': title, 'r': [list(r) for r in rows], 'f': foot}, ensure_ascii=False), quote=True)

def nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp

def _svg_open(width: int, height: int, cls: str, aria: str) -> str:
    return f'<div class="chart-wrap" style="--w:{width}"><svg class="{cls}" viewBox="0 0 {width} {height}" style="max-width:{width}px" role="img" aria-label="{escape(aria)}">'

def _col_path(x: float, y: float, w: float, h: float, r: float=4.0) -> str:
    if h <= 0:
        return ''
    r = min(r, w / 2, h)
    return f'M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z'

def columns(categories: list[str], series: list[dict], *, height: int=240, width: int=720, stacked: bool=True, fmt=lambda v: f'{v:,.1f}', tick_fmt=None, tick_labels: list[str] | None=None, tips: list[str] | None=None, emphasis: int | None=None, aria: str='') -> str:
    n = len(categories)
    if not n or not series:
        return '<div class="empty">No data for this period.</div>'
    top, bottom, left, right = (12, 26, 44, 8)
    ph = height - top - bottom
    pw = width - left - right
    totals = [sum((s['values'][i] or 0 for s in series)) if stacked else max((s['values'][i] or 0 for s in series)) for i in range(n)]
    ymax = nice_max(max(totals) or 1)
    band = pw / n
    bw = min(24.0, band * 0.62)
    tick_fmt = tick_fmt or (lambda v: f'{v:,.0f}')
    out = [_svg_open(width, height, 'chart', aria)]
    for k in range(5):
        v = ymax * k / 4
        y = top + ph - ph * k / 4
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{escape(tick_fmt(v))}</text>')
    for i, cat in enumerate(categories):
        cx = left + band * i + band / 2
        x = cx - bw / 2
        base = top + ph
        segs = [(s, s['values'][i] or 0) for s in series]
        if stacked:
            drawn = [(s, v) for s, v in segs if v > 0]
            for j, (s, v) in enumerate(drawn):
                h = ph * v / ymax
                last = j == len(drawn) - 1
                gap = 0 if last else 2.0
                color = s.get('color') or SERIES[series.index(s) % 3]
                if len(series) == 1 and emphasis is not None and (i != emphasis):
                    color = FAINT
                if last:
                    out.append(f'<path d="{_col_path(x, base - h, bw, h)}" fill="{color}"/>')
                else:
                    out.append(f'<rect x="{x:.1f}" y="{base - h + gap:.1f}" width="{bw:.1f}" height="{max(h - gap, 0):.1f}" fill="{color}"/>')
                base -= h
        else:
            k = len(segs)
            sub = bw / max(k, 1)
            for j, (s, v) in enumerate(segs):
                h = ph * v / ymax
                color = s.get('color') or SERIES[j % 3]
                out.append(f'<path d="{_col_path(x + j * sub + 1, top + ph - h, sub - 2, h)}" fill="{color}"/>')
        label = tick_labels[i] if tick_labels else cat
        if label:
            out.append(f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle" class="tick">{escape(label)}</text>')
        attr = tips[i] if tips else tip(cat, [(s['name'], s.get('color') or SERIES[series.index(s) % 3], fmt(s['values'][i] or 0)) for s in series], f'Total {fmt(totals[i])}' if stacked and len(series) > 1 else None)
        out.append(f'<rect class="hit" x="{left + band * i:.1f}" y="{top}" width="{band:.1f}" height="{ph}" fill="transparent" tabindex="0" data-tip="{attr}"/>')
    out.append('</svg></div>')
    return ''.join(out)

def legend(items: list[tuple[str, str]], shape: str='rect') -> str:
    parts = [f'<span class="lg"><i class="sw {shape}" style="background:{c}"></i>{escape(name)}</span>' for name, c in items]
    return f"""<div class="legend">{''.join(parts)}</div>"""

def meters(items: list[dict], *, fmt=lambda v: f'{v:,.1f}', color: str=SERIES[0]) -> str:
    out = ['<div class="meters">']
    for it in items:
        share = max(0.0, min(1.0, it.get('share') or 0))
        out.append(f'''<div class="meter tip-target" tabindex="0" data-tip="{tip(it['label'], [('', None, fmt(it['value']))], it.get('note'))}"><div class="meter-top"><span>{escape(it['label'])}</span><span class="num">{escape(fmt(it['value']))}{(' · ' + escape(it['note']) if it.get('note') else '')}</span></div><div class="meter-track"><div class="meter-fill" style="width:{share * 100:.1f}%;background:{it.get('color') or color}"></div></div></div>''')
    out.append('</div>')
    return ''.join(out)

def sparkbars(values: list[float], labels: list[str], *, width: int=300, height: int=64, fmt=lambda v: f'{v:,.1f}', highlight_last: bool=True) -> str:
    n = len(values)
    if not n:
        return ''
    vmax = max(values) or 1
    band = width / n
    bw = min(10.0, band * 0.7)
    out = [_svg_open(width, height, 'chart spark', 'value per day')]
    for i, v in enumerate(values):
        h = max((height - 4) * (v or 0) / vmax, 2 if v else 1)
        x = band * i + (band - bw) / 2
        color = SERIES[0] if highlight_last and i == n - 1 or (v and (not highlight_last)) else FAINT
        if not v:
            color = GRID
        out.append(f'<path d="{_col_path(x, height - h, bw, h, 2)}" fill="{color}"/>')
        out.append(f'''<rect class="hit" x="{band * i:.1f}" y="0" width="{band:.1f}" height="{height}" fill="transparent" tabindex="0" data-tip="{tip(labels[i], [('', None, fmt(v or 0))])}"/>''')
    out.append('</svg></div>')
    return ''.join(out)

def stack100(rows: list[dict], keys: list[tuple[str, str, str]], *, fmt=lambda v: f'{v:,.0f}') -> str:
    out = ['<div class="stack100">']
    for r in rows:
        total = sum((r['parts'].get(k, 0) or 0 for k, _, _ in keys))
        out.append(f"""<div class="s100-row"><div class="s100-label">{escape(r['label'])}</div><div class="s100-bar">""")
        for k, name, color in keys:
            v = r['parts'].get(k, 0) or 0
            if not v or not total:
                continue
            w = 100 * v / total
            out.append(f'''<div class="s100-seg tip-target" tabindex="0" style="width:{w:.2f}%;background:{color}" data-tip="{tip(r['label'], [(name, color, f'{fmt(v)} · {w:.0f}%')])}"></div>''')
        out.append(f'</div><div class="s100-total num">{fmt(total)}</div></div>')
    out.append('</div>')
    return ''.join(out)

def heat(row_labels: list[str], col_labels: list[str], matrix: list[list[int | None]], *, title: str='shared bonds') -> str:
    vmax = max((v or 0 for r in matrix for v in r)) or 1
    out = ['<table class="heat"><thead><tr><th></th>']
    out += [f'<th><span>{escape(c)}</span></th>' for c in col_labels]
    out.append('</tr></thead><tbody>')
    for i, rl in enumerate(row_labels):
        out.append(f'<tr><th>{escape(rl)}</th>')
        for j, v in enumerate(matrix[i]):
            if i == j or v is None:
                out.append('<td class="diag">·</td>')
                continue
            step = 5 - min(5, int((v or 0) / vmax * 5.999))
            bg = RAMP[step] if v else '#F4F5F9'
            ink = '#FFFFFF' if v and step <= 2 else '#14142B'
            out.append(f'''<td class="tip-target" tabindex="0" style="background:{bg};color:{ink}" data-tip="{tip(f'{rl} and {col_labels[j]}', [('', None, f'{v} {title}')])}">{v or ''}</td>''')
        out.append('</tr>')
    out.append('</tbody></table>')
    return ''.join(out)

def whole_shares(counts: list[int]) -> list[int]:
    total = sum(counts)
    if not total:
        return [0] * len(counts)
    raw = [c * 100 / total for c in counts]
    out = [int(p) for p in raw]
    for i in sorted(range(len(raw)), key=lambda i: -(raw[i] - out[i]))[:100 - sum(out)]:
        out[i] += 1
    return out
CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>'

def share_heat(cols: list[dict], groups: list[dict], total: dict | None=None) -> str:

    def cells(label: str, counts: list[int]) -> str:
        shares, top, total_n = (whole_shares(counts), max(counts) or 1, sum(counts))
        out = []
        for c, v, s in zip(cols, counts, shares, strict=True):
            if not v:
                t = tip(c['label'], [(label, None, 'not listed')])
                out.append(f'<td class="c zero tip-target" tabindex="0" data-tip="{t}"></td>')
                continue
            step = 5 - min(5, int(v / top * 5.999))
            ink = '#FFFFFF' if step <= 2 else '#14142B'
            t = tip(c['label'], [(label, None, f'{v} of {total_n} listings')], f'{v / total_n * 100:.1f}% of the category')
            out.append(f'<td class="c tip-target" tabindex="0" style="background:{RAMP[step]};color:{ink}" data-tip="{t}"><b>{s}%</b><small>{v}</small></td>')
        return ''.join(out)

    def sums(rs: list[dict]) -> list[int]:
        return [sum(col) for col in zip(*(r['counts'] for r in rs), strict=True)]

    def row(label: str, counts: list[int], chip: str | None, head: str='', cls: str='', attrs: str='') -> str:
        n = sum(counts)
        chip = f'<span class="chip warn">{escape(chip)}</span>' if chip else ''
        bar = f'<div class="valbar"><i style="width:{n / top_n * 100:.1f}%"></i></div>'
        return f'<tr class="{cls}"{attrs}><th class="cat">{head}<span>{escape(label)}</span>{chip}</th>{cells(label, counts)}<td class="num"><b>{n:,}</b>{bar}</td></tr>'
    top_n = max((sum(sums(g['rows'])) for g in groups), default=1) or 1
    out = ['<table class="heat share"><thead><tr><th class="l">Category</th>']
    for c in cols:
        logo = f'''<img class="plogo" src="{escape(c['logo'])}" alt="">''' if c.get('logo') else '<i class="plogo"></i>'
        note = f"""<small class="block">{escape(c['note'])}</small>""" if c.get('note') else ''
        out.append(f"""<th class="p">{logo}<span>{escape(c['label'])}</span>{note}</th>""")
    out.append('<th class="r">Listings</th></tr></thead>')
    for i, g in enumerate(groups):
        rid = f'cat-group-{i}'
        btn = f'''<button type="button" class="chevbtn" aria-expanded="false" aria-controls="{rid}" aria-label="Show the categories in {escape(g['label'])}">{CHEV}</button>'''
        out.append(f"<tbody>{row(g['label'], sums(g['rows']), g.get('chip'), btn, 'parent click', f' data-toggle={rid!r}')}</tbody>")
        out.append(f'<tbody id="{rid}" class="sub hidden">' + ''.join((row(r['label'], r['counts'], r.get('chip'), cls='child') for r in g['rows'])) + '</tbody>')
    if total:
        out.append(f"""<tbody><tr class="tot"><th class="cat">{escape(total['label'])}</th>{cells(total['label'], total['counts'])}<td class="num"><b>{sum(total['counts']):,}</b></td></tr></tbody>""")
    out.append('</table>')
    return ''.join(out)

def ranges(rows: list[dict], *, lo: float | None=None, hi: float | None=None, fmt=lambda v: f'{v:.2f}%') -> str:
    vals = [v for r in rows for _, v in r['points'] if v is not None]
    if not vals:
        return '<div class="empty">No shared bonds with yields.</div>'
    lo = min(vals) if lo is None else lo
    hi = max(vals) if hi is None else hi
    span = hi - lo or 1
    out = ['<div class="ranges">']
    for r in rows:
        pts = [(n, v) for n, v in r['points'] if v is not None]
        if not pts:
            continue
        a, b = (min((v for _, v in pts)), max((v for _, v in pts)))
        left, right = ((a - lo) / span * 100, (b - lo) / span * 100)
        out.append(f'''<div class="rg-row"><div class="rg-label" title="{escape(r['label'])}">{escape(r['label'])}</div><div class="rg-track"><div class="rg-line" style="left:{left:.1f}%;width:{max(right - left, 0.4):.1f}%"></div>''')
        for name, v in pts:
            x = (v - lo) / span * 100
            best = v == b
            out.append(f'''<div class="rg-dot tip-target{(' best' if best else '')}" tabindex="0" style="left:{x:.1f}%" data-tip="{tip(r['label'], [(name, SERIES[0] if best else SERIES[1], fmt(v))])}"></div>''')
        out.append(f'</div><div class="rg-gap num">{(b - a) * 100:.0f} bp<small>{a:.2f}–{b:.2f}%</small></div></div>')
    out.append('</div>')
    return ''.join(out)
