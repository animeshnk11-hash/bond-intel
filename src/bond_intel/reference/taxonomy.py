from __future__ import annotations
import re
from dataclasses import dataclass, field
SOVEREIGN = ('G-Sec', 'SDL', 'T-Bill', 'SGB')
CATEGORIES = ('G-Sec', 'SDL', 'T-Bill', 'SGB', 'PSU', 'Bank', 'NBFC/HFC', 'Corporate', 'Municipal', 'Other')
BOND_TYPES = ('Plain vanilla', 'Collateral-backed', 'Gold-backed', 'Guaranteed', 'Tax-free', 'Perpetual', 'Zero-coupon', 'Floating-rate', 'MLD', '54EC')
SENIORITY = ('Senior', 'Subordinated', 'Tier II', 'AT1', 'Unknown')
SECURITY = ('Secured', 'Unsecured', 'Unknown')
STAGGERED = ('Yes', 'No', 'Unknown')
COUPON_FREQS = ('monthly', 'quarterly', 'half_yearly', 'annual', 'on_maturity', 'other')
TYPE_PRECEDENCE = ['Gold-backed', 'MLD', 'Perpetual', 'Tax-free', 'Zero-coupon', 'Floating-rate', 'Guaranteed', '54EC', 'Collateral-backed']

@dataclass
class Taxonomy:
    category: str
    bond_type: str
    bond_flags: list[str] = field(default_factory=list)
    seniority: str = 'Unknown'
    security: str = 'Unknown'
    staggered: str = 'Unknown'

def _u(x) -> str:
    return (str(x) if x is not None else '').strip().upper()

def is_sovereign_isin(isin: str) -> bool:
    return not isin.upper().startswith(('INE', 'INF'))

def sovereign_category(isin: str, description: str | None=None, series: str | None=None) -> str:
    d, s = (_u(description), _u(series))
    if s == 'GB' or 'GOLD' in d or re.search('\\bSGB', d):
        return 'SGB'
    if s == 'TB' or 'T-BILL' in d or 'TBILL' in d or re.search('\\b(91|182|364)\\s*D', d):
        return 'T-Bill'
    if s == 'SG' or not isin.upper().startswith('IN00'):
        return 'SDL'
    return 'G-Sec'

def corporate_category(issuer: str | None, ownership: str | None, nature: str | None, sector: str | None) -> str:
    name, own, nat, sec = (_u(issuer), _u(ownership), _u(nature), _u(sector))
    if 'ILDM' in own or 'MUNICIPAL' in name:
        return 'Municipal'
    if nat == 'BANK' or re.search('\\bBANK\\b', name):
        return 'Bank'
    if 'PUBLIC SECTOR' in own or (re.search('\\bPSU\\b', own) and 'NON' not in own):
        return 'PSU'
    if nat.startswith('NBFC') or any((k in sec for k in ('NBFC', 'HOUSING FINANCE', 'FINANCIAL SERVICES', 'INVESTMENT COMPANY', 'MICROFINANCE'))):
        return 'NBFC/HFC'
    return 'Corporate'

def principal_events(cashflows: list[dict]) -> int:
    return sum((1 for c in cashflows if 'REDEMPTION' in _u(c.get('event')) or 'PRINCIPAL' in _u(c.get('event'))))

def classify(ins: dict, cashflows: list[dict] | None=None, series: str | None=None) -> Taxonomy:
    isin = ins['isin']
    desc = _u(ins.get('description'))
    if is_sovereign_isin(isin):
        cat = sovereign_category(isin, ins.get('description'), series)
        return Taxonomy(cat, 'Gold-backed' if cat == 'SGB' else 'Plain vanilla', ['Gold-backed'] if cat == 'SGB' else [], 'Unknown', 'Unknown', 'No')
    cat = corporate_category(ins.get('issuer_name'), ins.get('issuer_ownership'), ins.get('issuer_nature'), ins.get('business_sector'))
    flags: list[str] = []
    basis, nsdl_cat = (_u(ins.get('coupon_basis')), _u(ins.get('nsdl_category')))
    if 'MARKET LINKED' in nsdl_cat or re.search('\\bMLD\\b|MARKET\\s+LINKED', desc):
        flags.append('MLD')
    if ins.get('perpetual') or re.search('\\bPERP', desc):
        flags.append('Perpetual')
    if ins.get('tax_free') or 'TAX FREE' in desc or 'TAXFREE' in desc:
        flags.append('Tax-free')
    if 'ZERO' in basis or (ins.get('coupon_pct') in (0, None) and 'ZERO' in desc) or re.search('\\bZCB\\b|DEEP DISCOUNT', desc):
        flags.append('Zero-coupon')
    if 'FLOAT' in basis or re.search('\\bFRB\\b|FLOATING', desc):
        flags.append('Floating-rate')
    g = _u(ins.get('guarantee_raw'))
    if g and 'NOT GUARANTEED' not in g and (g not in ('-', 'NO')):
        flags.append('Guaranteed')
    if '54EC' in desc:
        flags.append('54EC')
    security = 'Secured' if _u(ins.get('secured_raw')).startswith('SECURED') else 'Unsecured' if _u(ins.get('secured_raw')).startswith('UNSECURED') else 'Unsecured' if 'UNSECURED' in desc else 'Secured' if 'SECURED' in desc else 'Unknown'
    if security == 'Secured':
        flags.append('Collateral-backed')
    bond_type = next((t for t in TYPE_PRECEDENCE if t in flags), 'Plain vanilla')
    sr = _u(ins.get('seniority_raw'))
    if re.search('ADDITIONAL TIER\\s*(1|I)\\b|\\bAT-?1\\b|TIER\\s*I\\s+PERP|TIER\\s*1\\s+PERP', desc):
        seniority = 'AT1'
    elif re.search('TIER\\s*(II|2)\\b|\\bT2\\b', desc):
        seniority = 'Tier II'
    elif sr.startswith('SENIOR'):
        seniority = 'Senior'
    elif sr.startswith('SUBORD') or 'SUBORDINATE' in desc:
        seniority = 'Subordinated'
    else:
        seniority = 'Unknown'
    if cashflows is None:
        staggered = 'Unknown'
    else:
        n = principal_events(cashflows)
        staggered = 'Yes' if n > 1 else 'No' if n == 1 else 'Unknown'
    return Taxonomy(cat, bond_type, flags, seniority, security, staggered)
