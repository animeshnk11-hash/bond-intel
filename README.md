# Bond Intel

Bond Intel is Blostem's bond-market intelligence tool. It follows India's bond market in one place: what traded on NSE and BSE each day, what the online bond platforms (OBPPs) offer, at what yields, how fast it sells, and where platforms overlap. Data is fetched from NSE, BSE, NSDL and the OBPPs by the Bond Intel worker.

**Product link (read-only): <https://bond-intel.vercel.app>**

This repository holds the public, read-only dashboard: five pages (Overview, Exchange, OBPP listings, Platforms, Category share) that read the Bond Intel database. It can only read; nothing can be changed from it. Data collection, the internal dashboard, the daily report and the API are not part of this repository.

## Documents

| Document | What |
|---|---|
| [PRD](docs/prd.md) | The problem, users, scope and requirements |
| [System design](docs/system-design.md) | The components at a high level and a day of data |
| [User flows](docs/user-flows.md) | Viewer, public reader, admin, daily report and API flows |
| [API](docs/api.md) | Every endpoint of the Bond Intel API, with fields and real examples |
| [API sequence diagrams](docs/api-sequence.md) | How a read and a Scrape now move through the system |

## Run the dashboard

It needs a read-only database connection: `pip install -r requirements-web.txt`, set `BI_DASHBOARD_DB_URL` and `BI_WEB_PUBLIC=1`, then
`uvicorn bond_intel.web.app:create_app --factory --app-dir src --port 8501`.
