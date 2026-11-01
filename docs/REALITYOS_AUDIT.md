# WeatherEdge technical audit (baseline for RealityOS)

Audited: `cobie12333/weatheredge`, commit `02fd2c8` (2026-10-17, "Document one-command live launch on antiX"), shallow clone, read-only. Nothing in the repo was modified or committed.

Evidence labels used below:
- **[CODE]** read directly from the source at that commit.
- **[RAN]** I executed it in a sandbox and saw the result.
- **[USER]** stated by you in earlier sessions; I could not check it.
- **[UNVERIFIED]** not checked. Treat as unknown.

## 0. What this audit could not see

- **No data.** `*.db` is gitignored, so I have not seen a single row. Row counts, date coverage, gaps and collector failure rates are unknown until `db_audit.py` (delivered with this file) is run on your machine.
- **No runtime.** Cron entries, logs and the antiX environment are not in the repo.
- **No live network.** My sandbox blocks `api.open-meteo.com` (proxy 403), so I could not test any endpoint or response shape. Every claim about external APIs is from reading your code or from public documentation I found by search, not from a successful call.
- **CI parity.** I replicated CI's fresh-DB and watchlist step on Python 3.13; CI uses 3.12. It passed.

## 1. What exists

Single-process, standard-library-only Python (no third-party dependencies, which is a strength for your 4 GB machine). 38 tracked files, about 4,200 lines of Python.

| Component | Path | Lines | Verdict |
|---|---|---:|---|
| Airport and market registry | `weatheredge/airports.py` | 20 | Reuse. Settlement-station discipline is the right pattern. |
| Schema v4 (legacy FACT tables plus `*_multi` tables, WAL) | `weatheredge/schema.sql` | 222 | Reuse as the raw-observation layer. Append-only, UNIQUE keys, `raw_payload` kept. |
| Multi-airport METAR collector | `multi_metar_collector.py` | 149 | Reuse. Catches all exceptions, logs missing stations. Best-written collector. |
| Market snapshot collector (Polymarket Gamma) | `market_collector.py` | 144 | Reuse after the error-handling fix in F4. |
| PWS discovery, quality gate, live activation | `pws_*.py`, `nearby_pws_watchlist.py` | about 600 | Reuse the quality-gate pattern (ID match, freshness, QC flag). Needs an API key to do anything. |
| Lag analysis (read-only, FACT) | `analysis/lag_analysis.py` | 828 | Reuse the method and the discipline (dated fix cutoff, "confirmation gap" wording). FACT-only and fed by a legacy table, see F5. |
| Backfills (IEM METAR, Open-Meteo Previous Runs, Polymarket prices-history) | `backfill_*.py` | about 500 | Reuse the Previous Runs idea: it is the right source for forecast skill. Currently FACT-only, GFS-only, leads 1 to 3 days. |
| Dashboard and sensor API | `dashboard.py`, `sensor_api.py` | 516 | Not needed for RealityOS. Leave alone. |
| Launcher and loop | `go_live.py`, `live_runner.py` | 148 | Works, but fragile, see F4. |
| CI | `.github/workflows/ci.yml` | 131 | Smoke tests only. Imports the package modules, never the legacy scripts. |
| Second package tree | `weatheredge/src/weatheredge/` | about 800 | Divergent duplicate, see F6. |

## 2. Data available (by code path, not by content)

| Domain | Tables | Written by | Notes |
|---|---|---|---|
| Airport METAR, 9 airports | `metar_multi` | `multi_metar_collector` (live loop) | `receipt_time` kept, good for latency work. 6-hour request window per poll. |
| FACT METAR, legacy | `metar_obs` | `metar_collector.py`, `backfill_iem_metar.py` | Not called by `live_runner`, see F5. |
| Market prices | `market_price_multi`, `market_price` (FACT only) | `market_collector`, `backfill_polymarket` | Snapshot per poll. UNIQUE key includes `fetched_at`, so repeated polls never collide. Intended, but means no de-duplication of unchanged prices. |
| Forecast vintages | `forecast_history` | `backfill_openmeteo` only | FACT, model `gfs_seamless`, leads 24/48/72 h. |
| PWS observations | `pws_obs_multi` | `pws_multi_collector`, `pws_rapid_collector` | Only for stations enabled after the live check. Needs `WEATHER_UNDERGROUND_API_KEY`. |
| Settlement truth | `outcome`, `outcome_multi` | **nothing in the repo** | See F2. |
| SAWS observations and forecasts | `saws_obs`, `saws_forecast` | `src/` tree only | Needs SAWS credentials. You told me research-tier access was still being requested [USER]. |
| `metar_parsed`, `forecast_history_multi` | | **nothing** (second one) | Tables exist, no writer for `forecast_history_multi`; `metar_parsed` is written only by the `src/` tree. |

Not present anywhere in the repo: electricity data, water or dam data, precipitation, solar radiation, cloud cover, humidity series for the cities, or any link between them. `grep` for `eskom`, `dws`, `electric` returns nothing.

## 3. Findings, most important first

### F1. The forecasting and calibration layer described in the README does not exist in the repo. [CODE]
README says: "probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals." Searching the whole tree finds no model, no Brier or CRPS code, no walk-forward code (the word "walk" appears only in the README), and no signal generator. The config constants `MIN_EDGE_THRESHOLD`, `MAX_SPREAD_THRESHOLD`, `MIN_LIQUIDITY_USD`, `CALIBRATION_MIN_SAMPLES`, `FORECAST_ERROR_WINDOW_DAYS` and `STARTING_CAPITAL` are defined and never used. What exists today is data collection plus one lag study. This is the central gap for the RealityOS objective.

### F2. There is no code that records settlement truth. [CODE]
No `INSERT` into `outcome` or `outcome_multi` anywhere. Either you fill them by hand (which would explain why the dashboard and sensor API read `outcome_multi`) or they are empty. Without labels nothing can be scored. `db_audit.py` section 5 will show which.

### F3. Forecast archive is thin and one-off. [CODE]
`forecast_history_multi` has no writer. `forecast_history` is filled only by a manual backfill, for FACT, one model, three leads. No live forecast vintage is captured going forward, and no other airport or city has any. A baseline-beating claim needs stored forecasts made before the outcome was known.

### F4. One uncaught exception stops all collection, and nothing restarts it. [RAN]
`live_runner.run_forever()` catches only `KeyboardInterrupt`. `market_collector.run()` catches only `URLError`, `TimeoutError` and `JSONDecodeError`. I simulated a `ConnectionResetError` (which can occur while reading a response) and it propagated out of `market_collector.run`. In that case the runner process exits, `go_live` sees a child exit, stops the dashboard, and returns 1. There is no supervisor or retry. `multi_metar_collector` is the only collector with a catch-all.

### F5. Two incompatible import conventions; the FACT lag analysis can go quiet silently. [RAN] [CODE]
- Eight modules (`metar_collector`, `backfill_*`, `migrate`, `backfill_cli`, `analysis/lag_analysis`) use absolute imports (`from db import ...`) plus `sys.path.insert(0, ".")`. Importing them from the repo root fails with `ModuleNotFoundError`; I reproduced it for three of them.
- The modules the launcher uses use relative imports and fail the other way when run from inside `weatheredge/`.
- CI runs `compileall` and imports only the relative-import modules, so a green CI says nothing about the eight legacy ones.
- `lag_analysis` reads the legacy `metar_obs` table. `live_runner` writes only `metar_multi`. If you now start through `go_live` and the old cron job for `metar_collector.py` is no longer running, the analysis table stops receiving live rows with no error. I cannot tell from the repo whether cron is still running. `db_audit.py` section 7 shows live rows per day.

### F6. Two overlapping packages with different behaviour. [CODE]
`weatheredge/src/weatheredge/` is a second implementation (version 2.0.0 in `pyproject.toml`) that shares the same `weatheredge.db` file as the flat package but differs in places:
- `TRACKED_BUCKET_COUNT` defaults to 5 there and 0 (keep every bucket) in the flat settings. If the `src` market code were ever run, it would discard buckets.
- `DB_PATH` can be overridden by an environment variable only in `src`.
- The PWS key is `WEATHER_COMPANY_API_KEY` in `src` and `WEATHER_UNDERGROUND_API_KEY` in the flat package. Set one and the other path silently has no key.
- `pyproject.toml` installs only the `src` package, while CI, the README and `go_live` use the flat one.
- It holds the only writers for `metar_parsed`, `saws_obs` and `saws_forecast`.
Which one is canonical needs a decision from you; I have not assumed.

### F7. FACT has two different coordinates. [CODE] [RAN]
`airports.py` says (-33.97403, 18.60433). `backfill_openmeteo.py` and `src/config.py` say (-33.9648, 18.6017). The distance between them is 1.05 km. I have not checked which is correct. The registry and the Open-Meteo backfill should share one source.

### F8. Test coverage is smoke-level. [CODE]
No tests directory. CI has inline assertions for schema creation, watchlist seeding, one PWS parser, the PWS quality gate, and a dashboard render. No tests for METAR parsing, market parsing, bucket handling, timezone logic, or analysis.

### F9. Secrets handling looks fine. [CODE]
No credential-like literals in tracked files. Keys come from environment variables. `POLYMARKET_WALLET_PRIVATE_KEY` is read in `src/config.py` and used nowhere. The README says paper trading only; I would still delete that line while the repo is paper-only.

## 4. Missing datasets for the weather → electricity → water chain

Access status is what I could confirm, not what I assume.

| Need | Source | What I confirmed | What I did not |
|---|---|---|---|
| Hourly national demand, available capacity, unplanned outages | Eskom Data Portal | Portal lists hourly demand and forecast, demand against available capacity, weekly peak demand, outages, renewables. Downloads go through a request form that emails a link, up to 5 years per request. | No machine-readable API found. File format and column names unseen. Terms of reuse unread. |
| Load-shedding status and schedules | EskomSePush API | The `load-shedding` Python library says SePush needs an API token. | Token terms and quota unknown. |
| Dam levels | DWS weekly State of Reservoirs report | Published weekly; media statements are PDFs. | Whether a structured file (XLS or CSV) exists for download. |
| Dam levels, structured | OurPower (independent aggregator of DWS data) | Site states the data comes from DWS; shows per-dam, per-province levels with a date. | Terms of use for scraping or reuse. It also lists an API page I did not read. |
| City-level weather history and forecasts | Open-Meteo | Free for non-commercial use, no key. Your repo already calls its Previous Runs API. | Live calls (sandbox blocked). Commercial licence terms matter if this becomes client work. |
| Catchment rainfall | not identified | | Needs a source. Airport METAR is not catchment rainfall. |
| Municipal water outages | municipal notices | | No structured source found. |

Context that changes what is worth predicting: Eskom reports no load shedding since 16 May 2025 and about 9.1 GW of unplanned outages at 31 March 2026 (down from 16.5 GW). A "load shedding this week" target is therefore almost always No. Better targets are continuous: weekly peak demand, headroom, available capacity, and local load reduction.

## 5. Proving "better than a baseline"

Define the baseline before the model, per target:

| Target | Baseline to beat | Why |
|---|---|---|
| Daily max temperature | Raw Open-Meteo forecast at the same lead; and climatology for the date | Shows whether any correction adds value |
| Daily or weekly peak electricity demand | Same weekday last week; seasonal mean by weekday | Eskom demand is strongly calendar-driven, so a weather model must beat a calendar model |
| Weekly dam level change | Persistence (no change) | Large dams move slowly, so persistence is hard to beat |

Evaluation rules:
1. Chronological walk-forward only. No shuffling.
2. Store every forecast before its outcome is known; score against the later outcome.
3. Report MAE or pinball loss, Brier score for event probabilities, reliability (calibration) curves, and whether the stated 80% interval actually contains about 80% of outcomes.
4. Report the sample size and a bootstrap interval on the improvement. Claim a win only if the interval excludes zero.
5. Hedge test, simulated only: define an exposure with numbers you supply (for example monthly energy or water cost for a named customer type), apply a rule-based hedge, and report variance and worst-month loss with and without it, out of sample. Hedge effectiveness = 1 − Var(hedged) / Var(unhedged).

## 6. Suggested order of work

Each step has a pass or fail test. Nothing new is built until the previous one passes.

- **Step 0: measure what you have (about an hour).** Run `db_audit.py` on the real database and share the report. Pass: you can state how many clean days of FACT, market and METAR data exist.
- **Step 1: stop silent failure.** Wrap each collector call in the loop with a catch-all plus logging, and add restart supervision to `go_live`. Decide whether `metar_obs` is still fed. Pass: a simulated network error no longer ends the loop.
- **Step 2: ground truth and forecast capture for FACT.** Write the `outcome` row from the settlement source and store a forecast vintage every day. Pass: every market day has a label and at least one prior forecast.
- **Step 3: first RealityOS test, on the link with the most history.** Request the Eskom hourly demand file (up to 5 years) and pull matching Open-Meteo history for Johannesburg, Cape Town and Mbombela. Fit weather → demand and compare with the calendar baseline, walk-forward. Pass: a confidence interval on the improvement, whichever way it falls. A null result is a result.
- **Step 4: water.** Weekly DWS levels against weather and demand, with persistence as the baseline. Expect a weak edge; test it rather than assume it.
- **Step 5: only then** a paper exposure and hedge ledger.

## 7. About the earlier "Weather Power Water Desk" artifact

That page is a hand-built model. Its coefficients (demand uplift per degree, pump capacity, reservoir size, outage hours) are my assumptions and were not fitted to any data. It is a way to explore the idea, not evidence for it. It should not count toward Step 3.
