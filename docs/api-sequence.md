# Bond Intel API: sequence diagrams

How a call moves through the system. Endpoints and fields: [API reference](api.md). Components: [System design](system-design.md).

## 1. Reading data (any GET)

Every read is answered from the database. The dashboard keeps a read for a minute, so repeated calls are fast, and any change made from the dashboard clears it.

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller (service or script)
    participant A as Bond Intel API
    participant D as Database
    C->>A: GET /api/v1/platforms<br/>X-API-Key: YOUR_API_KEY
    A->>A: Check the key (or the dashboard session)
    alt key missing or wrong
        A-->>C: 401 {"error": {"code": "bad_key"}}
    else key valid
        A->>D: Latest read and last run of every platform
        D-->>A: Rows
        A-->>C: 200 {"items": [...], "count": 11}
    end
```

The other reads follow the same path: `/platforms/{key}` (benchmark for the period plus every platform's latest read), `/platforms/{key}/listings` (one day's read, paged), `/bonds/{isin}` (the bond master plus each platform's latest listing), `/categories` (latest reads plus the category list).

## 2. Scrape now (POST, then follow it)

A Scrape now is an extra read: saved with its run and compared with the latest official read, never written into the day's snapshot.

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant A as Bond Intel API
    participant D as Database
    participant W as Bond Intel worker
    participant P as Online bond platform (OBPP)
    C->>A: POST /api/v1/scrapes {"site": "stablebonds"}
    A->>A: Check the key, or an admin session + X-CSRF-Token
    A->>D: Is the platform Live? Is a Scrape now of it already waiting?
    alt not a Live platform
        A-->>C: 422 not_live
    else already waiting
        A-->>C: 409 {"already_waiting": ["stablebonds"]}
    else
        A->>D: Queue one extra-read job per platform (with a scrape_id)
        A->>W: Start the online run now
        A-->>C: 202 {"scrape_id", "queued", "status_url"}
    end
    W->>D: Take the queued job
    W->>P: Read the platform's bond list
    P-->>W: Bonds on offer
    W->>D: Compare with the latest official read and save new / removed / sold out with the run
    loop until done or failed
        C->>A: GET /api/v1/scrapes/{scrape_id}
        A->>D: The runs of that scrape
        A-->>C: 200 {"status": "queued" | "running" | "done" | "failed"}
    end
    C->>A: GET /api/v1/extra-reads?site=stablebonds
    A-->>C: 200 {"items": [{"bonds_found", "changes": {"new", "removed", "sold_out"}}]}
```

The online run usually starts within a few minutes. If it cannot be started at once, the queued job runs at the next scheduled online run or on the backup worker, whichever comes first.

## 3. The dashboard's own Scrape now button

The buttons on the Sources page and on a platform's profile call the same endpoint with the signed-in session. Without JavaScript, the form posts to the dashboard instead and the result is the same.

```mermaid
sequenceDiagram
    autonumber
    actor U as Admin
    participant B as Browser (dashboard page)
    participant A as Bond Intel API
    U->>B: Scrape now (one platform or all), confirm
    B->>A: POST /api/v1/scrapes {"site"}<br/>session cookie + X-CSRF-Token
    A-->>B: 202 {"message"} (or 409 / 422 with a message)
    B-->>U: Banner with the message
```
