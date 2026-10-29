# Bond Intel: user flows

Who does what, step by step. Screens: [PRD](prd.md). Components: [System design](system-design.md).

## 1. Viewer: read the market and the platforms

```mermaid
flowchart TD
    S([Open the dashboard]) --> SI{Signed in?}
    SI -- No --> G[Sign in with a company account] --> AL{On the access list?}
    AL -- No --> X([Ask an admin for access])
    AL -- Yes --> O
    SI -- Yes --> O[Overview<br/>last trading day, top traded,<br/>highest yield per bucket]
    O --> E[Exchange<br/>pick period and filters]
    E --> E1[Top traded: sort, group,<br/>open a bond's details]
    E --> E2[Highest yield<br/>with the thin-trade guard]
    E --> E3[Trend: day, week, month]
    E1 --> DL[Download CSV / save the filters]
    O --> L[OBPP listings<br/>one row per bond on offer]
    L --> L1[Open a bond:<br/>compare its platforms]
    L --> L2[Changes: new, removed,<br/>sold out, yield moves]
    O --> P[Platforms<br/>benchmark, overlap, yield gaps]
    P --> P1[Open a platform's profile:<br/>mix, fast sellers, exclusives]
    O --> C[Category share<br/>categories split by platform]
    C --> C1[Open a group:<br/>categories only one platform has]
```

## 2. Public reader: the read-only link

```mermaid
flowchart LR
    S([Open the public link]) --> O[Overview]
    O --> E[Exchange] & L[OBPP listings] & P[Platforms] & C[Category share]
    E --> N([Read, filter, compare.<br/>Nothing can be changed or downloaded])
    L --> N
    P --> N
    C --> N
```

## 3. Admin: Scrape now

```mermaid
flowchart TD
    S([Need fresher platform data]) --> W{Where?}
    W -- Sources page --> A[Scrape now bar:<br/>all Live platforms or one]
    W -- Platforms page --> B[A platform's profile:<br/>Scrape now]
    A --> CF[Confirm: runs online now,<br/>saved as an extra read]
    B --> CF
    CF --> Q{Already waiting?}
    Q -- Yes --> M1([Banner: already waiting])
    Q -- No --> R[Queued; the online run starts]
    R --> M2([Banner: queued])
    M2 --> X[A few minutes later:<br/>Sources page, Extra reads]
    X --> X1[Bonds found and new / removed / sold out<br/>against the latest official read]
    X1 --> K([The 10:00 and 16:00 reads still happen<br/>and stay the day's snapshot])
```

## 4. Admin: add a platform

```mermaid
flowchart TD
    S([A new OBPP to follow]) --> U[Give its web address]
    U --> CF[Confirm the link once]
    CF --> LN[The worker learns the site:<br/>finds the bonds, how to page,<br/>which field is which]
    LN --> OK{Bonds found?}
    OK -- No --> F[Field report: what was not found] --> FX([Point it at the right page,<br/>learn again])
    OK -- Yes --> LV[Live: read at 10:00 and 16:00<br/>with every other platform]
    LV --> G{A later read looks broken?}
    G -- Yes --> H[Not saved; last good data stays; alert.<br/>Learned again automatically]
    H --> P3{3 failures in a row?}
    P3 -- Yes --> PA([Paused until an admin resumes it])
    P3 -- No --> LV
    G -- No --> LV
```

## 5. Team: the daily report

```mermaid
flowchart TD
    T([09:00 IST, a trading day]) --> B[The worker builds the report<br/>from the blocks switched on]
    B --> AI[AI writes 3–5 takeaways]
    AI --> CK{Every number, date and ISIN<br/>in the data?}
    CK -- No --> DR[Drop that takeaway]
    CK -- Yes --> KP[Keep it]
    DR --> EN{Enough good takeaways?}
    KP --> EN
    EN -- Yes --> SD[Send takeaways + tables]
    EN -- No --> ST[Send the tables only]
    SD --> CH([Team chat space])
    ST --> CH
```

## 6. Internal service: use the API

```mermaid
flowchart TD
    S([A service needs Bond Intel data]) --> K[An admin shares the API key<br/>through a secure channel]
    K --> R[Call GET endpoints with X-API-Key:<br/>platforms, listings, bonds, categories]
    R --> N{Need fresher data now?}
    N -- No --> D([Use the data])
    N -- Yes --> P[POST /api/v1/scrapes]
    P --> ST[Follow GET /api/v1/scrapes/scrape_id<br/>until done]
    ST --> EX[GET /api/v1/extra-reads] --> D
```
