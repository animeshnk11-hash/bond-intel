from __future__ import annotations
from pathlib import Path
from bond_intel.web import db
STATIC = Path(__file__).parent / 'static' / 'logos'

def files() -> dict[str, str]:
    return {p.stem: f'/static/logos/{p.name}' for p in STATIC.iterdir() if p.suffix in ('.png', '.svg')} if STATIC.is_dir() else {}

def logos() -> dict[str, str]:
    found = {k: v['data'] for k, v in (db.setting('platform_logos', {}) or {}).items() if isinstance(v, dict) and str(v.get('data', '')).startswith('data:image/')}
    return {**found, **files()}
