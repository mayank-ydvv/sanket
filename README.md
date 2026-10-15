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
