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

## Voice and SMS intake (Twilio)

- `POST /twilio/voice` answers with a Hindi + English prompt and records up to 60 s. If the
  caller says nothing, the call is reported with empty text, which the rules treat as a
  silent SOS (police, human review).
- `POST /twilio/recording` replies to Twilio immediately, then in the background downloads
  the MP3, transcribes it (Groq `whisper-large-v3`, ~0.6 s for a 10 s clip; Sarvam `saaras:v3`
  fallback for clips ≤ 30 s), and submits it as a `call` report with the detected language.
  A recording that cannot be transcribed is still submitted, so it reaches a human.
- `POST /twilio/sms` goes straight into the pipeline (the offline / no-data channel).
- Every webhook checks `X-Twilio-Signature` (HMAC-SHA1 over `PUBLIC_BASE_URL` + sorted
  params; verified against Twilio's documented example).

### Setup for a live call

1. **Twilio trial**: sign up at twilio.com (free trial credit). In the console, get a trial
   phone number with Voice + SMS. Copy the Account SID and Auth Token.
2. **Verify the demo phones**: Console → Phone Numbers → Verified Caller IDs. Trial accounts
   only send SMS/calls *to* verified numbers, and callers hear a short trial message first.
3. **Tunnel**: `brew install cloudflared`, then run
   `cloudflared tunnel --url http://localhost:8010` and copy the `https://….trycloudflare.com`
   URL (it changes on every run; an ngrok free static domain avoids that).
4. **Env** (`sanket/.env`): `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`,
   `PUBLIC_BASE_URL=<tunnel URL>`; restart the API.
5. **Webhooks**: on the number, set "A call comes in" → Webhook,
   `<tunnel>/twilio/voice`, HTTP POST; "A message comes in" → `<tunnel>/twilio/sms`, POST.
6. **Check**: `cd backend && .venv/bin/python -m scripts.twilio_check` posts a signed test
   SMS through the tunnel; then call the number.
7. *(Optional)* real SMS alerts: `MOCK_ALERTS=false` and phone numbers in `ALERT_CONTACTS`
   (verified numbers only on a trial).

Known limits: a Twilio trial number is usually a US number (Indian numbers need regulatory
approval), so calling it from an Indian phone is an international call for the caller.
Spoken numbers are a weak spot: in a test, "सेक्टर बासठ" (sector sixty-two) was transcribed as
"सेक्तर बासक", so the gazetteer cannot place it and the LLM's location extraction or a
dispatcher callback has to.

## Disaster mode and cost ticker

`POST /simulate/disaster?n=500&seconds=10&scenario=flood` (or the **Disaster mode** button)
streams a seeded flood surge through the real pipeline: 12 events across the district
(rooftop rescues, a bus in an underpass, a wall collapse, live wires in water, a building
with both a gas smell and a fire upstairs, looting, …) in five languages, with callers
calling back, panic and typos, one prank caller sending contradicting reports, two silent
SOS calls and some non-urgent noise. `GET /simulate/status` and `simulation.updated`
events show progress.

The **cost ticker** (`cost.updated`, at most 2×/s) prices the tokens the providers actually
report, per model, at list price, against a counterfactual of sending every report alone to
a large reasoning model (full prompt + reasoning output). Free tiers bill ₹0; both numbers
are list price, so the comparison holds at production scale.

Measured live (free tiers, 2026-10-17), 500 reports in 10 s:

| | |
|---|---|
| all 500 reports decided and on the board | 10.2 s after the first (pipeline 0.2 s behind intake) |
| LLM calls | 18–20 (343 reports revised by the LLM; the rest kept their local decision when free-tier limits hit) |
| cost at list price | ₹0.54–0.79 vs ₹477.75 for all-to-large-LLM (≈ 99.8% less; ₹1.6 vs ₹955 per 1,000 reports) |
| incidents | the 12 events → 12 large incidents (16–71 reports each), plus ~25 small ones: non-urgent complaints, the prank caller's decoys, both silent SOS calls (always kept separate), and singletons whose LLM call fell back |
| API memory | ~0.9 GB RSS with both models loaded |

The simulator reuses the corpus phrasings, including those the local model trained on, so
disaster mode shows system behaviour, not accuracy. Accuracy comes from the held-out test
set (`scripts/benchmark.py`, Phase 9).

## System 2: reasoning layer

A slower reasoning model looks only at complex incidents: those with ≥ 3 reports, two or more
distinct hazards, or another open incident within 300 m in the last 15 minutes (severity ≥ 3,
never silent SOS). It runs in the background (`app/reasoning/`), at most once per 20 s per
incident and only when the incident's reports or hazards changed, so dispatch never waits on it.

- **Input**: the incident's newest 30 reports plus nearby incidents (distance, hazards, two
  sample reports each), prompt `reasoning_v1`.
- **Output** (validated and grounded): linked hazards; a `combined_risk` only when hazards
  from different reports add up to more (e.g. "Fire on the 3rd floor combined with a strong
  gas smell: high risk of gas explosion or toxic smoke inhalation"); `merge_suggestions`, kept
  only if they name a nearby incident the model was actually shown; and a 3-line crew
  briefing (location/access, hazards, people at risk, "not stated" when unknown). Stored on
  the incident and audited with the model and prompt version.
- **Dispatcher**: the detail panel shows the linked-risk banner, the briefing and "Merge
  here" buttons (`POST /incidents/{id}/merge`). Merges are suggestions, never automatic.
- **Quotas**: both systems share one rate limiter per provider/model; System 1 runs first.
  A daily-quota 429 parks that provider for 15 min; an incident that cannot be reasoned
  backs off exponentially (20 s → 5 min); due incidents are taken most severe first.
- **Rerouting**: if a dispatched incident's department changes (LLM revision or override),
  the new department is alerted and the old alert stops escalating.

Live observation: right after a 500-report surge the free tiers were exhausted (Gemini's
daily quota, OpenRouter's upstream limit), so System 2 caught up over the following hours
mostly via Groq. With paid or self-hosted capacity it would keep pace; on free tiers,
briefings arrive late in a big surge.

## Benchmark (held-out test set, five approaches)

`python -m scripts.benchmark` (from `backend/`, real API keys) streams the 250 held-out test
reports (incl. 50 hidden during development) at 25/s through each approach and writes
`backend/data/benchmark.json` and [`docs/benchmark.md`](docs/benchmark.md). The app's
**Benchmark** section charts it.

| Approach | Triage acc | Hidden 50 | Recall | ₹ / 1,000 | LLM calls |
|---|---|---|---|---|---|
| keyword rules | 58.4% | 60% | 0.83 | 0 | 0 |
| local only | 52.8% | 54% | 0.93 | 0 | 0 |
| **Sanket hybrid** | **98.0%** | **98%** | **1.00** | **₹2.49** | 12 |
| fast LLM only | 97.2% | 96% | 0.99 | ₹3.13 | 20 |
| reasoning LLM only (gpt-oss-120b) | 92.0% | 98% | 0.97 | ₹22.69 | 46 |

Honest reading: the hybrid is the most accurate and the cheapest LLM approach, but its saving
over "fast LLM only" is small (≈ 20%) because the local model is confident (≥ 0.8) on only 5% of
held-out phrasings, so ~90% of reports still reach the LLM (see the gate table in the report).
Keyword rules beat the local classifier on its own. Latencies are dominated by free-tier
throttling. Pure-LLM approaches re-ask unanswered reports after quotas refill (the hybrid
never needs to, since its local answer stands in).

## Web app

React + Vite + Tailwind with a light/dark theme (remembered; follows the OS by default) and
Magic UI components (Blur Fade, Morphing Text, Animated Beam, Ripple, Magic Card, Bento Grid,
Pulsating Button, Dotted Map, Number Ticker, Animated List, Circular Progress, Flickering Grid,
Marquee, Hyper Text), adapted for Vite in `frontend/src/components/magicui/`.

- `/`: landing page (hero, live-feed demo, how it works, features, measured results).
- `/signup`, `/login`: dispatcher accounts. Passwords are scrypt-hashed in SQLite; sessions
  are HttpOnly HMAC-signed cookies; 5 failed logins per email per 5 min are throttled.
- `/app`: Overview (KPIs, disaster mode, live feed, cost), Incidents (ranked list + map +
  tabbed detail drawer), Alerts (waiting / no-ack / history), Benchmark & cost.

Citizen intake (`POST /reports`, Twilio webhooks) stays public; every dispatcher route and the
WebSocket require a session. `scripts/post_reports.py --email … --password …` logs in first.
