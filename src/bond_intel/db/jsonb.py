from __future__ import annotations
import json
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from psycopg.types.json import Jsonb

def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)
dumps = partial(json.dumps, default=_default, ensure_ascii=False)

def jsonb(obj) -> Jsonb:
    return Jsonb(obj, dumps=dumps)

def plain(obj):
    return json.loads(dumps(obj))
