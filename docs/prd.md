# Bond Intel: product requirements

| | |
|---|---|
| Product | Bond Intel, Blostem's bond-market intelligence tool |
| Owner | Product (Bonds) |
| Status | Live: internal dashboard, public read-only dashboard, daily report, API |
| Links | Public read-only dashboard: <https://bond-intel.onrender.com> · Internal dashboard: for the Bonds team |
| Updated | 29 Oct 2026 |

See also: [System design](system-design.md) · [User flows](user-flows.md) · [API](api.md) · [API sequence diagrams](api-sequence.md)

## 1. Problem

Blostem's Bonds team needs to know, every day, what India's bond market is doing and what competing online bond platforms (OBPPs) are offering:

- Which bonds traded on NSE and BSE, how much, and at what yields.
- Which bonds each OBPP lists, at what yields and minimum amounts, which are new, which sold out, and how fast they sell.
- Where platforms overlap, which bonds or issuer categories only one platform has, and who offers the best yield on a shared bond.

Doing this by hand means opening 11 platform sites and two exchanges every day and copying numbers into sheets. It is slow, misses changes between visits, and keeps no history.

## 2. Goals

1. One place with each day's exchange trades and every OBPP's catalogue, kept for 90 days.
2. Fresh OBPP data twice a day without anyone doing anything, and on demand when needed.
3. A short daily report the team reads in its chat space, with numbers that are always right.
4. A new platform added from its web address alone, with one confirmation.
5. The data available to other internal services through an API, and to people outside the team as a read-only view.

## 3. Users

| User | Needs |
|---|---|
| **Viewer** (Bonds sales, BD, product) | Browse the market and the platforms, filter, compare, download, read the daily report |
| **Admin** (Bonds product owner) | Everything a viewer does, plus: add and pause platforms, Scrape now, schedules, report contents and chat spaces, rating buckets, users |
| **Public reader** (anyone with the public link) | See the same reading pages, without signing in; change nothing |
| **Internal service** | Read platforms, listings, bonds and categories as JSON; start a Scrape now |

## 4. Scope

### 4.1 Data

| Source | What | When (IST) |
|---|---|---|
| NSE, BSE | Each trading day's bond trades: order book and BSE RFQ, per bond and exchange: value, trades, high, low, published yields | 08:00 (previous day) and 19:15–21:30 (same day), weekdays |
| NSDL | The bond master and each newly traded bond's details: issuer, category, sector, rating and agency, coupon, maturity, security, seniority, cash flows; rating actions | 05:00, 09:15, 17:01, 21:00 |
| OBPPs (11; 10 Live) | Every bond each platform offers, with the fields that platform shows: yield, coupon, maturity, rating, price, minimum amount, units left or % sold, status | 10:00 and 16:00 daily, and on demand (Scrape now) |

Requirements:

- **R1.** A platform is read with the fields it shows; nothing is filled in from another source. A field it does not show is reported as "not found on this site".
- **R2.** One official read per platform per day (the last good read). A Scrape now is an extra read, kept with its run and compared with the latest official read; it never replaces the official read.
- **R3.** A read that looks broken (no bonds, under half the usual count, fields suddenly empty) is not saved; the last good data stays, an alert goes out, and after 3 failures in a row the platform pauses.
- **R4.** History is kept 90 days.

### 4.2 Dashboard (internal)

| Page | Must show |
|---|---|
| Overview | The last trading day against the day before and the 5-day average; 22 days of value traded; value by rating bucket; top traded bonds; highest yield per bucket |
| Exchange | Every bond traded over a period: Top traded (sort, group, details), Highest yield (with a thin-trade guard), Trend by day, week and month. Filters for period, rating, category, market, terms and structure; CSV download; saved filters |
| OBPP listings | One row per bond on offer across platforms, opening to a comparison. Changes: new, removed, sold out, back on sale, units sold, yield moves |
| Platforms | The benchmark: catalogue, launches, speed of sale, median yield, A- or better share, issuers, exclusives, best-price share; rating mix, yield gaps on shared bonds, overlap; a profile per platform |
| Category share | Each issuer category's listings split by platform, grouped, with categories only one platform has called out |
| Sources (admins) | Health of every source and task, alerts, the queue; per platform: run, re-learn, accept a new shape, go live, pause, add; **Scrape now** (all Live platforms or one) and the extra reads |
| Daily report | Schedule, blocks, live preview, chat spaces, history |
| Settings (admins) | Rating buckets, thin-trade guard, retention, users, schedules, holidays, recent activity |

- **R5.** Sign-in with a company account that is on the access list; roles Admin and Viewer.
- **R6.** Filters live in the address, so a view can be bookmarked or shared; nothing is stored in the browser.

### 4.3 Public read-only dashboard

- **R7.** Overview, Exchange, OBPP listings, Platforms and Category share, for anyone with the link, no sign-in.
- **R8.** It can only read: no admin, report, sign-in or API pages exist there, downloads are off, and search engines are asked not to index it.
- **R9.** Its published code and docs reveal nothing about how data is collected or where secrets live.

### 4.4 Daily report

- **R10.** Each trading day at 09:00 to the team chat space(s): the blocks switched on (default: market totals, top traded, OBPP fast sellers, yield moves), headed by 3–5 AI-written takeaways.
- **R11.** Every number, date and ISIN in a takeaway must appear in the report's data, or the takeaway is dropped; without enough good takeaways the report goes with its tables only.
- **R12.** Each date is sent once; a report missed while the worker was down goes out late, marked delayed, until 13:00.

### 4.5 Adding a platform

- **R13.** An admin gives the platform's web address and confirms it once; the platform is learned and goes Live on the same schedule, with no code per site and no separate approval step.

### 4.6 API

- **R14.** `GET` platforms, a platform's profile, a day's listings (paged), a bond across platforms, categories (overlapping or unique, with their bonds); `POST` Scrape now and follow it. Details: [API](api.md).
- **R15.** Authenticated with one shared key (or the dashboard session); on the internal dashboard only.

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Freshness | Every Live platform read at 10:00 and 16:00; Scrape now starts the online run at once |
| Availability | Scheduled jobs run online; a backup worker takes over when the online run cannot; a job missed while nothing ran catches up once |
| Resilience | A hung or crashed platform page cannot hold up the others: a crashed tab is tried again up to 5 times, a page visit stops after 5 minutes, a platform run after 20 |
| Politeness | At most one request every 2 seconds per site; a site that pushes back is read more slowly |
| Security | Secrets never in code, repositories or the browser; the public copy can only read; the API needs a key |
| Accuracy | Numbers are computed from the data; the AI only words the takeaways and is checked |

## 6. Out of scope (now)

- Computing yields the exchanges do not publish.
- Platforms that show bonds only after a login (public pages only).
- NSE RFQ trades as a separate source.

## 7. Success measures

| Measure | How it is seen |
|---|---|
| Every Live platform has an official read every day | Platforms page: snapshot days per platform; Sources page: failures in a row |
| The daily report goes out every trading day | Daily report page: history |
| Report numbers are correct | Takeaways dropped by the number check (report history) |
| A new platform goes Live without code | Platforms added from the web address (Sources page history) |
