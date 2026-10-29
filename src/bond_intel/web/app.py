from __future__ import annotations
import importlib
import logging
import os
from datetime import datetime, time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from bond_intel.config import IST
from bond_intel.web import auth, db, fmt, sched
log = logging.getLogger('bond_intel.web')
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / 'templates'))
templates.env.filters.update(fmt.FILTERS)
templates.env.globals.update(bond_label=fmt.bond_label, rating=fmt.rating, delta_pct=fmt.delta_pct, is_num=fmt.is_num, share=fmt.share, web_url=fmt.web_url)
NAV = [('overview', '/', 'Overview', 'grid'), ('exchange', '/exchange', 'Exchange', 'chart'), ('obpp', '/obpp', 'OBPP listings', 'store'), ('platforms', '/platforms', 'Platforms', 'compare'), ('categories', '/categories', 'Category share', 'layers'), ('sources', '/sources', 'Sources', 'globe'), ('report', '/report', 'Daily report', 'send'), ('settings', '/settings', 'Settings', 'gear')]
PUBLIC_PAGES = ('overview', 'exchange', 'obpp', 'platforms', 'categories')
PAGES = PUBLIC_PAGES + ('sources', 'report', 'settings')

def pages_here() -> tuple[str, ...]:
    return PUBLIC_PAGES if auth.public_view() else PAGES
templates.env.globals['has_page'] = lambda name: name in pages_here()
NEXT_JOBS = {'exchange.eod': 'Exchange EOD', 'obpp.scrape': 'Platform listings', 'report.send': 'Daily report'}
LAYOUT_SQL = "\nSELECT (SELECT value FROM cfg.setting WHERE key = 'worker_lease') AS lease,\n       (SELECT count(*) FROM ops.event WHERE kind = 'alert' AND status = 'open'\n           AND severity IN ('warn', 'critical')) AS alerts,\n       (SELECT coalesce(jsonb_agg(jsonb_build_object('job', job_type, 'status', status, 'times', times_local,\n                                                     'rule', day_rule)), '[]'::jsonb)\n          FROM ops.task WHERE times_local IS NOT NULL AND status = 'live'\n           AND job_type IN ('exchange.eod', 'obpp.scrape', 'report.send')) AS tasks\n"
LAYOUT_Q = ('rows', LAYOUT_SQL, {})

def _layout() -> tuple[dict, int]:
    r = db.row(LAYOUT_SQL) or {}
    lease = r.get('lease') or {}
    until = lease.get('lease_until')
    alive = bool(until) and datetime.fromisoformat(until) > datetime.now(IST)
    nxt = None
    hol = sched.holidays()
    for t in r.get('tasks') or []:
        task = {'status': t['status'], 'day_rule': t['rule'], 'times_local': [time.fromisoformat(x) for x in t['times']]}
        s = sched.next_run(task, hol)
        if s and (nxt is None or s < nxt[0]):
            nxt = (s, NEXT_JOBS.get(t['job'], t['job']))
    return ({'alive': alive, 'next': nxt}, int(r.get('alerts') or 0))

def page(request: Request, template: str, active: str, user: auth.User, **ctx) -> HTMLResponse:
    try:
        worker, alerts = _layout()
    except Exception:
        log.exception('layout status')
        worker, alerts = ({'alive': False, 'next': None}, 0)
    return templates.TemplateResponse(request, template, {'user': user, 'nav': [n for n in NAV if n[0] in pages_here() and (user.is_admin or n[0] not in ('sources', 'settings'))], 'active': active, 'worker': worker, 'alert_count': alerts, 'csrf': auth.csrf_token(request), 'now': datetime.now(IST), 'flash': request.session.pop('flash', None), **ctx})

def flash(request: Request, text: str, kind: str='ok') -> None:
    request.session['flash'] = {'text': text, 'kind': kind}

def allowed_hosts() -> list[str]:
    hosts = [h.strip().lower() for h in os.environ.get('BI_WEB_HOSTS', 'localhost,127.0.0.1').split(',')]
    if auth.public_view() or auth.oauth_config() is not None:
        hosts.append(os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip().lower())
    return [h for h in hosts if h] or ['localhost', '127.0.0.1']

def create_app() -> FastAPI:
    public = auth.public_view()
    app = FastAPI(title='Bond Intel', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=auth.session_secret(), session_cookie='bi_session', same_site='lax', https_only=public, max_age=14 * 24 * 3600)
    if public:

        @app.middleware('http')
        async def read_only(request: Request, call_next):
            if request.method not in ('GET', 'HEAD') or request.url.path.endswith('/download.csv'):
                return PlainTextResponse('This is a read-only copy of Bond Intel.', status_code=403)
            response = await call_next(request)
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            return response
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
    app.mount('/static', StaticFiles(directory=str(HERE / 'static')), name='static')

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith('/api/'):
            code = {400: 'bad_request', 401: 'unauthorised', 403: 'forbidden', 404: 'not_found', 405: 'method_not_allowed'}.get(exc.status_code, 'error')
            return JSONResponse({'error': {'code': code, 'message': str(exc.detail)}}, status_code=exc.status_code)
        if exc.status_code in (302, 303) and exc.headers and exc.headers.get('Location'):
            return RedirectResponse(exc.headers['Location'], status_code=303)
        return templates.TemplateResponse(request, 'error.html', {'status': exc.status_code, 'detail': exc.detail}, status_code=exc.status_code)

    @app.get('/robots.txt', response_class=PlainTextResponse)
    async def robots():
        return 'User-agent: *\nDisallow: /\n'
    for name in pages_here():
        app.include_router(importlib.import_module(f'bond_intel.web.pages.{name}').router)
    return app
app = create_app
