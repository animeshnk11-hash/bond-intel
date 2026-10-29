from __future__ import annotations
import pandas as pd
WINDOW_KINDS = {'D1': 'Day', 'R5': 'Last 5 trading days', 'R22': 'Last 22 trading days', 'WTD': 'Week to date', 'MTD': 'Month to date', 'CUSTOM': 'Custom range'}
METRICS = {'value': 'Traded value (Rs)', 'qty': 'Quantity (units)', 'trades': 'Number of trades'}
SOVEREIGN_CATEGORIES = ('G-Sec', 'SDL', 'T-Bill', 'SGB')
LATEST_DAY_SQL = 'SELECT max(trade_date) FROM mkt.trade_daily'
WINDOW_SQL = 'SELECT start_date, end_date FROM mkt.window_bounds(:kind, :asof, :dfrom, :dto)'
AGG_SQL = "\nWITH agg AS (\n    SELECT l.isin,\n           sum(l.qty) AS qty, sum(l.value_inr) AS value_inr, sum(l.trades) AS trades,\n           count(DISTINCT l.trade_date) AS days_traded,\n           max(l.high_clean) AS high_clean, min(l.low_clean) AS low_clean,\n           max(l.high_dirty) AS high_dirty, min(l.low_dirty) AS low_dirty,\n           (array_agg(l.ytm_pct ORDER BY l.trade_date DESC, l.value_inr DESC NULLS LAST)\n                FILTER (WHERE l.ytm_pct IS NOT NULL))[1] AS ytm_pct,\n           array_agg(DISTINCT l.exchange || ' ' || CASE l.segment WHEN 'ORDER_BOOK' THEN 'OB' ELSE l.segment END) AS legs,\n           bool_or(l.high_px100 IS NOT NULL AND l.high_clean IS NULL) AS price_partial,\n           max(l.trade_date) AS last_trade_date\n      FROM mkt.v_trade_leg l\n     WHERE l.trade_date BETWEEN :s AND :e\n       AND l.exchange = ANY(:exchanges) AND l.segment = ANY(:segments)\n     GROUP BY l.isin)\nSELECT a.*, p.description AS security_name, p.issuer_name, p.category, p.bond_type, p.seniority, p.security,\n       p.staggered, p.coupon_pct, p.coupon_freq, p.maturity_date, p.rating_code, p.rating_agency,\n       coalesce(p.bucket, CASE WHEN mkt.is_sovereign(a.isin) THEN 'SOVEREIGN' ELSE 'BELOW_BBB' END) AS bucket\n  FROM agg a LEFT JOIN ref.v_bond_profile p USING (isin)\n"
TOTALS_SQL = '\nSELECT trade_date, sovereign, value_inr, trades, isins, prev_value_inr, prev_trades, avg5_value_inr, avg5_trades\n  FROM mkt.v_market_totals WHERE trade_date BETWEEN :s AND :e ORDER BY trade_date\n'
LEG_TOTALS_SQL = '\nSELECT exchange, segment, sum(value_inr) AS value_inr, sum(trades) AS trades\n  FROM mkt.v_trade_leg WHERE trade_date = :d AND NOT sovereign GROUP BY 1, 2 ORDER BY 1, 2\n'
LEGS_OF_ISIN_SQL = '\nSELECT trade_date, exchange, segment, qty, value_inr, trades, high_px100, low_px100, px_type, high_clean, low_clean,\n       high_dirty, low_dirty, ai_px100, ytm_pct\n  FROM mkt.v_trade_leg WHERE isin = :isin AND trade_date BETWEEN :s AND :e ORDER BY trade_date DESC, exchange, segment\n'
METRIC_COLUMN = {'value': 'value_inr', 'qty': 'qty', 'trades': 'trades'}

def filter_frame(frame: pd.DataFrame, buckets: list[str] | None, categories: list[str] | None) -> pd.DataFrame:
    f = frame
    if buckets:
        f = f[f['bucket'].isin(buckets)]
    if categories:
        f = f[f['category'].isin(categories) | f['category'].isna() & ('Other' in categories)]
    return f

def top_traded(frame: pd.DataFrame, metric: str='value', n: int=5) -> pd.DataFrame:
    col = METRIC_COLUMN[metric]
    return frame.sort_values([col, 'value_inr'], ascending=False, na_position='last').head(n)

def passes_guard(frame: pd.DataFrame, guard: dict) -> pd.Series:
    mode = (guard or {}).get('mode', 'min_value')
    if mode == 'min_trades':
        return frame['trades'].fillna(0) >= int(guard.get('min_trades', 3))
    if mode == 'none':
        return pd.Series(True, index=frame.index)
    return frame['value_inr'].fillna(0) >= float(guard.get('min_value_inr', 1000000))

def top_yield_by(frame: pd.DataFrame, key: str, guard: dict, n: int=3, order: list[str] | None=None) -> pd.DataFrame:
    ytm = pd.to_numeric(frame['ytm_pct'], errors='coerce')
    f = frame[ytm.gt(0) & ytm.lt(50) & passes_guard(frame, guard)]
    f = f.sort_values('ytm_pct', ascending=False).groupby(key, sort=False).head(n)
    if order:
        f = f.assign(_o=f[key].map({k: i for i, k in enumerate(order)}).fillna(len(order)))
        f = f.sort_values(['_o', 'ytm_pct'], ascending=[True, False]).drop(columns='_o')
    return f
