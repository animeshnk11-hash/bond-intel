from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from bond_intel.config import IST
ON_TIME_GRACE = timedelta(minutes=3)

def day_allowed(d: date, rule: str, is_holiday: Callable[[date], bool]) -> bool:
    if rule == 'daily':
        return True
    if d.weekday() >= 5:
        return False
    if rule == 'weekdays':
        return True
    if rule == 'trading_days':
        return not is_holiday(d)
    raise ValueError(f'unknown day_rule {rule!r}')

def slots_between(times_local: list[time], rule: str, after: datetime, until: datetime, is_holiday: Callable[[date], bool]=lambda _d: False) -> list[datetime]:
    after, until = (after.astimezone(IST), until.astimezone(IST))
    out: list[datetime] = []
    d = after.date()
    while d <= until.date():
        if day_allowed(d, rule, is_holiday):
            for t in sorted(times_local):
                s = datetime.combine(d, t, tzinfo=IST)
                if after < s <= until:
                    out.append(s)
        d += timedelta(days=1)
    return out

@dataclass
class Plan:
    enqueue: list[tuple[datetime, str]]
    skipped: list[datetime]
    new_last_slot: datetime | None

def plan_slots(slots: list[datetime], now: datetime, policy: str, window: timedelta) -> Plan:
    if not slots:
        return Plan([], [], None)

    def trigger(s: datetime) -> str:
        return 'schedule' if now - s <= ON_TIME_GRACE else 'catchup'
    if policy == 'each':
        keep = [s for s in slots if now - s <= window]
    elif policy == 'once':
        keep = [slots[-1]] if now - slots[-1] <= window else []
    elif policy == 'skip':
        keep = [slots[-1]] if now - slots[-1] <= ON_TIME_GRACE else []
    else:
        raise ValueError(f'unknown catchup_policy {policy!r}')
    return Plan([(s, trigger(s)) for s in keep], [s for s in slots if s not in keep], slots[-1])

def next_slot(times_local: list[time], rule: str, after: datetime, is_holiday: Callable[[date], bool]=lambda _d: False) -> datetime | None:
    found = slots_between(times_local, rule, after, after + timedelta(days=15), is_holiday)
    return found[0] if found else None
