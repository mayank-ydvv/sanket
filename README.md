# Sanket — AI emergency triage agent

Turns a flood of messy, multilingual emergency reports into a short, ranked list of
de-duplicated incidents, each routed to the right department.

> Work in progress — built phase by phase. Full setup, architecture and demo guide land in Phase 10.

## Run locally

```bash
cp .env.example .env            # then set CALLER_SALT to a long random string
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
(cd backend && .venv/bin/python -m scripts.gen_data && .venv/bin/python -m scripts.train_local)
(cd backend && .venv/bin/uvicorn app.main:create_app --factory --port 8010)
(cd frontend && npm install && npm run dev)   # http://localhost:5190
```

Post a report:

```bash
curl -X POST localhost:8010/reports -H 'content-type: application/json' \
  -d '{"text":"aag lagi hai sector 18","channel":"sms","caller":"+919999999999"}'
```

Tests: `cd backend && .venv/bin/pytest -q`

## Local classifier (System 1)

`scripts/gen_data.py` builds `data/train.jsonl` (600) and `data/test.jsonl` (250) from a
multilingual corpus (English, Hinglish, Hindi, Tamil, Bengali): about 60% emergencies,
25% non-urgent and 15% prank/noise, with 30 hand-written hard cases (sarcasm, silent SOS,
keyword traps, the same event phrased differently). Every third event phrasing per language
is held out for the test set, so test sentences are never seen in training. 50 test rows
are hidden for the final benchmark.

`scripts/train_local.py` fits one shared TF-IDF feature union (char 2–5 + word 1–2) and
three LogisticRegression heads (emergency, department, severity), then prints test
metrics and latency to `backend/artifacts/local_v1.metrics.json`.

## Decision pipeline (System 1)

Every report: **local classifier → fast LLM (only if local confidence < 0.8) → safety rules**.

- **Fast LLM** (`app/decision/llm.py`): uncertain reports from all in-flight batches are
  pooled for up to 300 ms / 25 items and sent as one JSON-mode request, so n uncertain
  reports cost about n/25 calls. Providers are tried in `LLM_CHAIN` order — by default
  Groq (≈1 s) → each Gemini model in `GEMINI_MODELS` (separate free quotas) → OpenRouter →
  any OpenAI-compatible endpoint (e.g. Jev) — each with its own RPM / TPM / output-TPM
  buckets and an explicit output cap. A 429/5xx puts that provider in a jittered
  exponential cooldown and the batch moves on to the next provider at once; hard errors
  (bad key, retired model) park it. The `decision_v2` prompt uses short keys and omits
  default fields (~45 output tokens per report), because output length is what sets both
  latency and free-tier quotas. Output is validated item by item (complete items are
  salvaged even from a truncated reply); missing or invalid items are re-asked once, then
  the local answer stands with `needs_human_review=true`.
- **Rules** (`app/decision/rules.py`) always run last and can only raise severity or add
  review flags: a life-safety severity floor of 3, silent SOS (tap codes, Morse, keyboard
  mash, "can't talk", empty calls → police + human review), hazard tags, and a prank score
  from repeat callers with contradicting reports (rank only, never dismissal).
- **Lanes**: `auto` (emergency, both probabilities ≥ 0.9), `confirm`, `review` (< 0.5,
  silent SOS, or flagged).

Score a running server against 100 held-out test reports:
`cd backend && .venv/bin/python -m scripts.post_reports --n 100`

## Geocoding and incident clustering

- **Location**: the LLM's `location_text`, else a regex/gazetteer extractor ("Sector N",
  known landmarks, Devanagari/Bengali/Tamil digits). Geocoding goes gazetteer → in-memory
  LRU → SQLite `geocode_cache` (misses cached too) → Nominatim, behind one global 1 req/s
  limiter, bounded to the district viewbox, with a custom User-Agent. If the limiter queue
  is too long the report stays "location unconfirmed" instead of stalling triage.
- **Index** (`app/cluster/index.py`): open incidents updated in the last 30 min, bucketed in
  ~1 km grid cells. A located report checks its cell + 8 neighbours, then a ≤ 1 km haversine
  test; an unlocated report checks the 50 most recent incidents of its department. Candidates
  are scored with one matrix-vector product over unit centroids + a department bonus.
  Centroids are running sums (renormalised), expiry is a lazy min-heap. Measured: 5.6 µs per
  lookup at 200 open incidents vs 7.4 µs at 20,000 (constant density).
- **Embeddings**: multilingual MiniLM over `"<department> <hazards>: <text>"`. The canonical
  English tags matter: raw MiniLM scores the same event in Hinglish vs English at ~0.48,
  so untagged text fragmented a 500-report surge into 39–51 incidents; tagged, it gives 13–16.
- **Twin merge**: after a join moves a centroid or location, the incident is re-matched; an
  incident it now matches (typically one started by an unlocated report) is merged into
  the larger one and audited. Dispatchers can split any report back out
  (`POST /incidents/{id}/split`).
- **Severity**: max report severity, +1 (cap 5) past 10 reports or when a report mentions
  children, trapped people or spreading fire.
- **Acceptance**: 500 multilingual reports about 12 events → 13, 13 and 14 incidents on three
  seeds (`tests/test_incidents.py`), ~3 s each including embeddings. The default join
  threshold is 0.70 (+0.15 department bonus): at 0.75 one seed produced 15.

Known limit: a report with no usable location can only be matched by department and text,
so when several same-department events are open at once (~7–9% of surge reports in tests)
it may join the wrong one. These incidents are marked "location unconfirmed" for callback.

## Live board, map and alerts

- **Progressive decisions**: every report is decided by the local model + rules and placed on
  the board immediately (`refining: true` if uncertain). The fast LLM re-checks uncertain
  reports in the background; when it answers, the report is revised in place, and if its
  department changed or it was finally located, it is re-clustered into the right incident.
- **WebSocket** (`/ws`): events `report.created|updated`, `incident.created|updated`,
  `alert.sent|updated`, delivered as one `batch` message at most every 100 ms (≤ 10/s).
  Updates to the same entity within a window coalesce; `*.updated` events carry only the
  fields that changed since the last send.
- **Board**: incidents ranked by severity, then waiting time, with department, confidence,
  lane (auto-dispatch / confirm / human review), silent SOS, prank, needs-review, location and
  alert badges. **Map**: Leaflet pins coloured by severity, clusters coloured by their most
  severe incident, centred on the demo district. **Detail**: merged reports (original text,
  source, confidence, rules fired), alerts, audit trail; Confirm, Acknowledge, Override, Split.
- **Lanes per incident**: any silent SOS → human review; else one report that clears the
  auto-dispatch gate (both probabilities ≥ 0.9) → auto-dispatch; else review if at least half
  the reports are flagged, otherwise one-click confirm.
- **Alerts** (`app/alerts/`): auto-dispatch or one-click confirm alerts the first contact on
  the department's ladder (mock sender, or Twilio SMS over the shared client). One scheduler
  loop over a min-heap of deadlines escalates anything unacknowledged after 90 s to the next
  contact; timers resume after a restart. Every alert, ack, escalation and override is audited.
- **Endpoints**: `POST /incidents/{id}/confirm | /ack | /override | /split`, `GET /alerts`.
