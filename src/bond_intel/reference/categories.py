from __future__ import annotations
import re
from dataclasses import dataclass, field
NSDL_GOVT = {'G-Sec': 'Central government securities (G-Sec)', 'T-Bill': 'Treasury bills', 'SDL': 'State development loans (SDL)'}

def issuer_key(name: str | None) -> str:
    s = re.sub('[^A-Z0-9]+', ' ', (name or '').upper().replace('&', ' AND '))
    s = re.sub('\\bLIMITED\\b', 'LTD', s)
    return ' '.join(re.sub('\\bPRIVATE\\b', 'PVT', s).split())

def _by_isin(isin: str) -> str | None:
    if re.match('IN002\\d{3}[XYZ]', isin):
        return 'Treasury bills'
    if isin.startswith('IN00'):
        return 'Central government securities (G-Sec)'
    if re.match('IN\\d{2}', isin):
        return 'State development loans (SDL)'
    if isin.startswith('INE') and isin[7:9] == '15':
        return 'Securitised debt (PTC)'
    return None

@dataclass
class Categories:
    order: list[str] = field(default_factory=list)
    group: dict[str, str] = field(default_factory=dict)
    issuers: dict[str, str] = field(default_factory=dict)
    bonds: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_setting(cls, doc: dict | None) -> Categories:
        doc = doc or {}
        cats = doc.get('categories') or []
        issuers: dict[str, str] = {}
        for i in doc.get('issuers') or []:
            issuers.setdefault(issuer_key(i['name']), i['category'])
        return cls(order=[c['category'] for c in cats], group={c['category']: c['group'] for c in cats}, issuers=issuers, bonds={k: v['category'] for k, v in (doc.get('bonds') or {}).items()})

    def of(self, isin: str, issuer: str | None=None, nsdl_issuer: str | None=None, nsdl_category: str | None=None) -> str | None:
        return self.bonds.get(isin) or (self.issuers.get(issuer_key(nsdl_issuer)) if nsdl_issuer else None) or (self.issuers.get(issuer_key(issuer)) if issuer else None) or NSDL_GOVT.get(nsdl_category or '') or _by_isin(isin)

    def pending(self, rows: list[dict]) -> list[dict]:
        out: dict[str, dict] = {}
        for r in rows:
            if self.of(r['isin'], r.get('issuer'), r.get('nsdl_issuer'), r.get('nsdl_category')):
                continue
            name = r.get('nsdl_issuer') or r.get('issuer') or r['isin']
            e = out.setdefault(issuer_key(name), {'issuer': name, 'isins': set(), 'platforms': set()})
            e['isins'].add(r['isin'])
            e['platforms'].add(r['platform'])
        return sorted(({**e, 'isins': sorted(e['isins']), 'platforms': sorted(e['platforms'])} for e in out.values()), key=lambda e: (-len(e['isins']), e['issuer']))
