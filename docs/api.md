# Bond Intel API

The JSON API of the internal dashboard. It returns the same figures the dashboard pages show (platforms, listings, bonds, categories) and can start a **Scrape now**. Version 1, under `/api/v1`.

- **Where it runs:** the internal dashboard only, at `https://<internal-dashboard-host>/api/v1`. The public read-only site has no API: every `/api` address there is `404`.
- **Format:** JSON in and out, UTF-8. Dates are `YYYY-MM-DD`; times are ISO 8601 in IST (`+05:30`). Percentages are plain numbers (`11.85` means 11.85 %). Amounts are rupees.
- **Examples:** every response below is a real one from 29 Oct 2026, shortened where a list is long (`…`).

See also: [API sequence diagrams](api-sequence.md) · [System design](system-design.md) · [PRD](prd.md)

## Authentication

Every request must be authenticated in one of two ways. Use the first for scripts and other services.

| Caller | How | Notes |
|---|---|---|
| Another service or a script | Header `X-API-Key: <YOUR_API_KEY>` | One shared key for all callers, issued by an admin and shown once. A new key replaces the old one within a minute. Never put the key in code, a repository or a ticket |
| The dashboard itself | Its signed-in session (cookie) | A `POST` also sends the page's form token in `X-CSRF-Token`. The dashboard's Scrape now buttons work this way |

```http
GET /api/v1/platforms HTTP/1.1
Host: <internal-dashboard-host>
X-API-Key: <YOUR_API_KEY>
```

The key can read everything and start a scrape. A signed-in **viewer** can read; starting a scrape needs an **admin** session or the key.

## Errors

Every error has the same shape:

```json
{ "error": { "code": "unknown_platform", "message": "No Live or paused platform 'nosuch'." } }
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | A dashboard session sent a `POST` without a valid `X-CSRF-Token` |
| 401 | `no_key` / `bad_key` | No key and no session / the key is wrong |
| 403 | `admins_only` | A viewer session tried to start a scrape |
| 404 | `not_found`, `unknown_platform`, `unknown_bond`, `unknown_scrape`, `no_snapshot`, `no_data` | Nothing at that address, or nothing for those parameters |
| 409 | — | `POST /scrapes`: every platform asked for already has a Scrape now waiting (the body says which) |
| 422 | `bad_parameter`, `bad_isin`, `bad_site`, `not_live` | A parameter is out of range or not a Live platform |
| 503 | — | `GET /health`: the database did not answer |

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | [`/api/v1/health`](#get-apiv1health) | Is the service up, and when does the worker run next |
| GET | [`/api/v1/platforms`](#get-apiv1platforms) | Every platform: status, last snapshot, bonds, last run |
| GET | [`/api/v1/platforms/{key}`](#get-apiv1platformskey) | One platform's profile over a period |
| GET | [`/api/v1/platforms/{key}/listings`](#get-apiv1platformskeylistings) | A platform's official read for a day, paged |
| GET | [`/api/v1/bonds/{isin}`](#get-apiv1bondsisin) | One bond: reference data and every platform that lists it |
| GET | [`/api/v1/categories`](#get-apiv1categories) | Issuer categories: overlapping or unique, with the bonds under each |
| POST | [`/api/v1/scrapes`](#post-apiv1scrapes) | Scrape now: an extra read of one platform or all Live ones |
| GET | [`/api/v1/scrapes/{scrape_id}`](#get-apiv1scrapesscrape_id) | Progress of one Scrape now |
| GET | [`/api/v1/extra-reads`](#get-apiv1extra-reads) | The latest Scrape now results |

---

### GET /api/v1/health

No parameters.

| Field | Type | Meaning |
|---|---|---|
| `status` | `"ok"` \| `"degraded"` | `degraded` (HTTP 503) when the database does not answer |
| `database` | `"ok"` \| `"unreachable"` | |
| `time` | datetime | Server time (IST) |
| `open_alerts` | integer | Open warning and critical alerts |
| `worker.running` | boolean | A worker holds the lease right now |
| `worker.next_run` | object \| null | `at` (datetime) and `job` (name) of the next scheduled run people wait for |

```json
{
  "status": "ok", "database": "ok", "time": "2026-10-29T15:06:48.328477+05:30", "open_alerts": 15,
  "worker": { "running": true, "next_run": { "at": "2026-10-29T16:00:00+05:30", "job": "Platform listings" } }
}
```

### GET /api/v1/platforms

No parameters. Every online bond platform that is not a draft.

| Field | Type | Meaning |
|---|---|---|
| `items[].key` | string | Platform key, used in the other paths (`stablebonds`, `wint`, …) |
| `items[].name` | string | Display name |
| `items[].status` | `live` \| `paused` \| `off` | Live platforms are read on schedule |
| `items[].url` | string | The page the platform is read from |
| `items[].last_snapshot` | date \| null | Day of the latest official read |
| `items[].bonds_listed` / `bonds_live` | integer | Bonds in that read / of them, on sale |
| `items[].last_run` | object \| null | `status`, `at`, `bonds` and `extra_read` (true when it was a Scrape now) of the latest finished run |
| `count` | integer | Number of items |

```json
{
  "items": [
    { "key": "altifi", "name": "Altifi", "status": "live", "url": "https://altifi.ai/",
      "last_snapshot": "2026-10-29", "bonds_listed": 40, "bonds_live": 40,
      "last_run": { "status": "ok", "at": "2026-10-29T12:36:50.204470+05:30", "bonds": 40, "extra_read": false } },
    …
  ],
  "count": 11
}
```

### GET /api/v1/platforms/{key}

| Parameter | In | Type | Default | Meaning |
|---|---|---|---|---|
| `key` | path | string | — | Platform key |
| `period` | query | `7` \| `30` \| `90` | `7` | Days ending at the latest snapshot day |

| Field | Type | Meaning |
|---|---|---|
| `platform` | object | `key`, `name`, `status`, `url` |
| `period` | object | `days`, `from`, `to` |
| `summary` | object | The benchmark row: `bonds_live`, `bonds_listed`, `launches`, `sold_out`, `median_ytm`, `pct_a_or_better`, `issuers`, `exclusives`, `best_price_share` (% of shared bonds where this platform offers the highest yield), `units_sold_per_day`, `pct_sold_per_day` (% sold points gained per day, summed over bonds), `sales_published` (the site shows units left or % sold), `last_snap` |
| `mix` | object | Bonds by `Rating`, `Issuer type`, `Years to maturity`, `Coupon`, `Yield (YTM)`, `Minimum investment`: each a list of `{label, bonds}` |
| `overlap` | list | `{platform, shared}`: bonds this platform shares with each other one, most first |
| `best_yield_on_shared` | object | `best`, `priced`, `behind`, `behind_median_bp` (median basis points behind the best yield) |
| `exclusive` | list | Bonds no other platform lists: `isin`, `issuer`, `rating`, `ytm_pct`, `label`, highest yield first |
| `fast_sellers` | list | `isin`, `label`, `units_sold`, `pct_sold_up` |
| `sold_out` | list | `isin`, `label`, `sold_out_on`, `days_to_sell` |

```json
{
  "platform": { "key": "stablebonds", "name": "Stable Bonds", "status": "live", "url": "https://www.stablebonds.in/" },
  "period": { "days": 7, "from": "2026-10-23", "to": "2026-10-29" },
  "summary": { "bonds_live": 118, "bonds_listed": 118, "launches": 21, "sold_out": 0, "median_ytm": 9.75,
               "pct_a_or_better": 83.9, "issuers": 71, "exclusives": 60, "best_price_share": 22.4,
               "units_sold_per_day": 657.6, "pct_sold_per_day": 108.14, "sales_published": true, "last_snap": "2026-10-29" },
  "mix": { "Rating": [ { "label": "Sovereign", "bonds": 8 }, { "label": "AAA", "bonds": 13 }, { "label": "AA", "bonds": 30 }, … ],
           "Issuer type": [ { "label": "NBFC/HFC", "bonds": 96 }, { "label": "Corporate", "bonds": 8 }, … ], … },
  "overlap": [ { "platform": "BondScanner", "shared": 24 }, { "platform": "Wint Wealth", "shared": 18 }, … ],
  "best_yield_on_shared": { "best": 13, "priced": 58, "behind": 45, "behind_median_bp": 50.0 },
  "exclusive": [ { "isin": "INE861D07034", "issuer": "Shalibhadra Finance Limited", "rating": "BBB-", "ytm_pct": 11.85,
                   "label": "Shalibhadra Finance 11.20% Oct '28" }, … ],
  "fast_sellers": [ { "isin": "INE861D07034", "label": "Shalibhadra Finance 11.20% Oct '28", "units_sold": 4083, "pct_sold_up": 100.0 }, … ],
  "sold_out": []
}
```

### GET /api/v1/platforms/{key}/listings

| Parameter | In | Type | Default | Meaning |
|---|---|---|---|---|
| `key` | path | string | — | Platform key |
| `date` | query | `YYYY-MM-DD` | latest | Day of the official read (one per platform per day, kept 90 days) |
| `limit` | query | 1–500 | 100 | Page size |
| `offset` | query | 0–100000 | 0 | Rows to skip |

Sorted by yield, highest first. A field the platform does not show is `null`.

| Field | Type | Meaning |
|---|---|---|
| `platform`, `date`, `total`, `limit`, `offset` | | The read and the page |
| `items[].isin`, `issuer`, `bond_name` | string | |
| `items[].coupon_pct`, `ytm_pct` | number | % a year |
| `items[].coupon_freq` | `monthly` \| `quarterly` \| `half_yearly` \| `annual` \| `on_maturity` \| `other` | |
| `items[].maturity_date` | date | |
| `items[].face_value_inr`, `price_per_unit_inr`, `min_investment_inr` | number | ₹ |
| `items[].clean_price_100`, `dirty_price_100` | number | Per ₹100 of face value |
| `items[].rating_code`, `rating_agency`, `rating_outlook` | string | As the platform shows them |
| `items[].category`, `seniority`, `security`, `bond_type`, `staggered`, `bond_flags` | | As the platform shows them |
| `items[].units_available`, `pct_sold` | number | Where the platform publishes them |
| `items[].status` | `live` \| `sold_out` \| `upcoming` \| `closed` \| `unknown` | |
| `items[].first_seen_on` | date | First day the bond was seen on this platform |

```json
{
  "platform": "stablebonds", "date": "2026-10-29", "total": 118, "limit": 1, "offset": 0,
  "items": [
    { "isin": "INE0NES07147", "issuer": "Keertana Finserv Limited", "bond_name": "Keertana Finserv Limited",
      "coupon_pct": 11.4, "coupon_freq": "monthly", "staggered": null, "maturity_date": "2027-05-26",
      "face_value_inr": 100000.0, "rating_code": "BBB+", "rating_agency": "IND", "rating_outlook": "Stable",
      "category": "Financial Services", "seniority": "Senior", "security": null, "bond_type": "VANILLA", "bond_flags": [],
      "ytm_pct": 11.85, "clean_price_100": 99.97508, "dirty_price_100": 99.97508, "price_per_unit_inr": 30051.31,
      "min_investment_inr": 30051.31, "units_available": 1511, "pct_sold": 79.0, "status": "live", "first_seen_on": "2026-10-24" }
  ]
}
```

### GET /api/v1/bonds/{isin}

| Parameter | In | Type | Meaning |
|---|---|---|---|
| `isin` | path | string | An Indian ISIN (`IN` + 9 letters or digits + a check digit), any case |

| Field | Type | Meaning |
|---|---|---|
| `reference` | object \| null | The bond master (from NSDL): `issuer_name`, `description`, `instrument_type`, `category`, `business_sector`, `rating_code`, `rating_agency`, `coupon_pct`, `coupon_freq`, `maturity_date`, `face_value_inr`, `seniority`, `security`, `bond_type` |
| `platforms` | list | Each platform that lists it in its latest read: `platform_key`, `platform`, `snap_date`, `status`, `ytm_pct`, `coupon_pct`, `price_per_unit_inr`, `clean_price_100`, `min_investment_inr`, `units_available`, `pct_sold`, `rating_code`, `first_seen_on`; best yield first |
| `yield_range` | object \| null | `best`, `lowest`, `spread_bp` across the platforms selling it |

```json
{
  "isin": "INE0NES07147",
  "reference": { "isin": "INE0NES07147", "issuer_name": "KEERTANA FINSERV LIMITED",
                 "description": "11.40% SECURED RATED LISTED REDEEMABLE NON-CONVERTIBLE DEBENTURE DATE OF MATURITY 26/05/2027",
                 "instrument_type": "Debentures", "category": "NBFC/HFC",
                 "business_sector": "Non-Banking Financial Company (NBFC) (IN050101004)", "rating_code": "BBB+",
                 "rating_agency": "IND", "coupon_pct": 11.4, "coupon_freq": "monthly", "maturity_date": "2027-05-26",
                 "face_value_inr": 50000.0, "seniority": "Unknown", "security": "Secured", "bond_type": "Collateral-backed" },
  "platforms": [
    { "platform_key": "stablebonds", "platform": "Stable Bonds", "snap_date": "2026-10-29", "status": "live", "ytm_pct": 11.85,
      "coupon_pct": 11.4, "price_per_unit_inr": 30051.31, "clean_price_100": 99.97508, "min_investment_inr": 30051.31,
      "units_available": 1511, "pct_sold": 79.0, "rating_code": "BBB+", "first_seen_on": "2026-10-24" },
    { "platform_key": "wint", "platform": "Wint Wealth", "snap_date": "2026-10-29", "status": "live", "ytm_pct": 10.0,
      "coupon_pct": 11.4, "price_per_unit_inr": 30202.5932, "clean_price_100": 100.5816, "min_investment_inr": null,
      "units_available": 1021, "pct_sold": 4.85, "rating_code": "BBB+", "first_seen_on": "2026-10-22" }
  ],
  "yield_range": { "best": 11.85, "lowest": 10.0, "spread_bp": 185 }
}
```

### GET /api/v1/categories

No parameters. From every Live or paused platform's latest read, each bond's issuer category (NBFC lending segments, public-sector institutions, corporates by sector, sovereign).

| Field | Type | Meaning |
|---|---|---|
| `as_of` | date | Latest snapshot day |
| `platforms[]` | list | `key`, `name`, `status`, `snapshot`, `listings` |
| `summary` | object | `categories`, `overlapping` (on 2+ platforms), `unique` (on one), `unclassified_listings` (new issuers not classified yet) |
| `categories[].category`, `group` | string | |
| `categories[].listings`, `bonds` | integer | Listings across platforms / distinct bonds |
| `categories[].platforms` | object | Listings per platform key |
| `categories[].overlap` | `overlapping` \| `unique` \| null | null for "Not yet classified" |
| `categories[].only_on` | string \| null | The platform, when unique |
| `categories[].items[]` | list | The bonds: `isin`, `issuer`, `platforms` (keys); most-listed first |

```json
{
  "as_of": "2026-10-29",
  "platforms": [ { "key": "indiabonds", "name": "IndiaBonds", "status": "live", "snapshot": "2026-10-29", "listings": 155 }, … ],
  "summary": { "categories": 30, "overlapping": 28, "unique": 2, "unclassified_listings": 7 },
  "categories": [
    { "category": "Gold loans", "group": "NBFC & HFC lending", "listings": 151, "bonds": 102,
      "platforms": { "indiabonds": 9, "bondscanner": 23, "wint": 31, … }, "overlap": "overlapping", "only_on": null,
      "items": [ { "isin": "INE101Q07CB5", "issuer": "MUTHOOT MCRED LIMITED",
                   "platforms": ["digifinn", "altifi", "aspero", "bondscanner", "grip", "indiabonds"] }, … ] },
    { "category": "Metals & mining", "group": "Corporates", "listings": 1, "bonds": 1, "platforms": { "wint": 1 },
      "overlap": "unique", "only_on": "wint",
      "items": [ { "isin": "INE205A08053", "issuer": "VEDANTA LIMITED", "platforms": ["wint"] } ] },
    …
  ]
}
```

### POST /api/v1/scrapes

Starts a **Scrape now**: one extra read per platform, run online at once. It is saved with its run, not in the day's snapshot; the scheduled 10:00 and 16:00 reads still happen and stay official. Needs the key or an admin session.

Body (optional; no body means all Live platforms):

```json
{ "site": "all" }
```

| Field | Type | Meaning |
|---|---|---|
| `site` | `"all"` \| platform key | Which platforms |

Responses:

| HTTP | When | Body |
|---|---|---|
| 202 | Queued | `scrape_id`, `queued` (keys), `already_waiting` (keys skipped because a Scrape now of theirs is still waiting), `online_run_started` (boolean), `online_run` (what happened when starting it), `message`, `status_url` |
| 409 | Every platform asked for was already waiting | The same fields; `scrape_id` is null |
| 422 | `bad_site` / `not_live` | Error |

```json
{
  "scrape_id": "<scrape-id>", "queued": ["stablebonds"], "already_waiting": [],
  "online_run_started": true, "online_run": "<how the online run was started>",
  "message": "Scrape now queued for stablebonds: <…>. It is saved as an extra read; the 10:00 and 16:00 runs still happen.",
  "status_url": "/api/v1/scrapes/<scrape-id>"
}
```

(Placeholders: no Scrape now was started for this document. A `scrape_id` is 12 hexadecimal characters.)

### GET /api/v1/scrapes/{scrape_id}

| Field | Type | Meaning |
|---|---|---|
| `scrape_id` | string | |
| `status` | `queued` \| `running` \| `done` \| `failed` \| `partly_failed` | Across its platforms |
| `platforms[]` | list | One per platform, as in [extra reads](#get-apiv1extra-reads) |

`404 unknown_scrape` for an id that does not exist.

### GET /api/v1/extra-reads

| Parameter | In | Type | Default | Meaning |
|---|---|---|---|---|
| `site` | query | platform key | all | One platform's |
| `limit` | query | 1–100 | 20 | Newest first |

| Field | Type | Meaning |
|---|---|---|
| `items[].job_id`, `scrape_id` | | The run, and the Scrape now it belongs to |
| `items[].platform_key`, `platform` | string | |
| `items[].status` | `queued` \| `running` \| `done` \| `failed` \| `cancelled` | |
| `items[].requested_by`, `requested_at`, `finished_at` | | Who started it and when |
| `items[].bonds_found` | integer \| null | Bonds in the extra read |
| `items[].compared_with` | date \| null | The official read it was compared with |
| `items[].changes` | object \| null | `new`, `removed`, `sold_out` against that read (when done) |
| `items[].reason` | string \| null | Why it failed, if it did |
| `count` | integer | |

```json
{ "items": [], "count": 0 }
```

(No Scrape now had run when this was written. A done item has the shape
`{ "platform_key": "<key>", "status": "done", "bonds_found": <n>, "compared_with": "<date>", "changes": { "new": <n>, "removed": <n>, "sold_out": <n> }, … }`.)
