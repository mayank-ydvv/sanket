# Sanket benchmark

Held-out test set: 250 synthetic reports in 5 languages (50 of them never used during development), streamed at 25 reports/s. Run 2026-10-18 14:40 IST. Free-tier APIs; cost is list price for the tokens the providers reported.

| Approach | Triage acc | Hidden-50 | Emergency P / R / F1 | Dept acc | Severity MAE | Silent SOS | p50 / p95 latency | LLM calls | ₹ per 1,000 |
|---|---|---|---|---|---|---|---|---|---|
| keyword rules | 0.584 | 0.600 | 0.72 / 0.83 / 0.77 | 0.624 | 0.87 | 0/4 | 0 / 0 ms | 0 | 0.00 |
| local only | 0.528 | 0.540 | 0.76 / 0.93 / 0.84 | 0.516 | 0.86 | 0/4 | 6 / 11 ms | 0 | 0.00 |
| Sanket hybrid | 0.980 | 0.980 | 0.99 / 1.00 / 0.99 | 0.940 | 0.54 | 4/4 | 6561 / 61573 ms | 12 | 2.49 |
| fast LLM only | 0.972 | 0.960 | 0.99 / 0.99 / 0.99 | 0.924 | 0.52 | 4/4 | 62830 / 104555 ms | 20 | 3.13 |
| reasoning LLM only | 0.920 | 0.980 | 0.95 / 0.97 / 0.96 | 0.848 | 0.42 | 3/4 | 300838 / 596104 ms | 46 | 22.69 |

**Triage accuracy** = emergency call right and, for real emergencies, the right department.

## Per-language triage accuracy

| Approach | bn | en | hi | hinglish | ta |
|---|---|---|---|---|---|
| keyword rules | 0.84 | 0.58 | 0.67 | 0.38 | 0.48 |
| local only | 0.52 | 0.40 | 0.57 | 0.58 | 0.58 |
| Sanket hybrid | 1.00 | 0.98 | 0.94 | 0.98 | 1.00 |
| fast LLM only | 1.00 | 0.96 | 0.94 | 0.96 | 1.00 |
| reasoning LLM only | 1.00 | 0.91 | 0.92 | 0.83 | 0.96 |

## Local confidence gate (what the local model could decide alone)

| Gate | Share of reports kept local | Triage accuracy on those |
|---|---|---|
| 0.5 | 48% | 0.697 |
| 0.6 | 33% | 0.780 |
| 0.7 | 16% | 0.902 |
| 0.8 | 5% | 1.000 |
| 0.9 | 0% | 0.000 |

## Notes

- **Sanket hybrid**: 9% of reports decided without an LLM call (local model + rules)
- **Sanket hybrid**: Latency here is to the *final* decision. Every report is on the board with its local decision within ~10 ms; uncertain ones are revised when the LLM answers.
- Reasoning LLM only uses openai/gpt-oss-120b (a reasoning model; gemini-3.5-flash as fallback) in batches of 10 to fit free-tier limits; one report per call would cost and wait more.
- Each LLM approach starts after a 65s pause and may wait up to 60s for free-tier quota, so its latency includes throttling, as it would in a real surge on free tiers. LLM-only approaches re-ask unanswered reports after quotas refill (no fallback of their own); the hybrid never needs to, because its local answer stands in.
- Keyword rules, local only, fast LLM only and reasoning LLM only run without the safety rules; the hybrid includes them, as Sanket does in production.
