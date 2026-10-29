from __future__ import annotations
from datetime import date, datetime
from bond_intel.config import IST
from bond_intel.web import db
from bond_intel.worker.scheduler import next_slot

def holidays(kind: str='trading') -> set[date]:
    doc = db.setting('holidays', {}) or {}
    return {date.fromisoformat(v['date']) for v in doc.values() if v.get('kind') == kind and v.get('date')}

def next_run(task: dict, hol: set[date] | None=None, now: datetime | None=None) -> datetime | None:
    if task.get('status') != 'live' or not task.get('times_local'):
        return None
    hol = holidays() if hol is None else hol
    return next_slot(list(task['times_local']), task['day_rule'], now or datetime.now(IST), lambda d: d in hol)
NEXT_OF_SQL = "SELECT status, times_local, day_rule FROM ops.task WHERE job_type = :j AND status = 'live'"

def next_of(job_type: str) -> datetime | None:
    hol = holidays()
    runs = [next_run(t, hol) for t in db.rows(NEXT_OF_SQL, j=job_type)]
    runs = [r for r in runs if r]
    return min(runs) if runs else None
