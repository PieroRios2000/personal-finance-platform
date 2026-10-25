---
type: decision
phase: 3
status: accepted
date: 2026-10-17
---

# ADR 0051: Claude as a per-transaction category classifier -- cheap, but well behind the trained model on quality

## Context

The deferred Phase 3 item (`tasks/backlog.md`): how would an LLM (Claude) compare against the
trained classifier (ADR 0044) as a per-transaction categorizer -- on quality, latency and cost,
not just "could it work." The owner approved sending his real transaction descriptions to the
Claude API specifically for this comparison (the only place in this project anything leaves the
local machine other than the GCP demo's own data).

## Decision

**The trained model stays. Claude is not adopted as the categorizer, now or as a fallback.**

Real run against the owner's 543 trusted (reviewed) labels -- the same set README already reports
the trained model's honest headline number against (macro-F1 **0.49**, 3-fold merchant-grouped CV)
-- classifying each description zero-shot (the 15-category list from `gold.dim_category`, no
examples, `max_tokens=30`), real cost and latency from `response.usage`, never estimated:

| Model | Macro-F1 | Parse failures | Mean latency | Measured cost (543 calls) | Projected $/month\* |
|---|---|---|---|---|---|
| Trained model (ADR 0044, reference) | **0.49** | n/a | n/a (batch, local) | n/a (no API) | $0 |
| `claude-haiku-4-5` | 0.217 | 2 | 0.68s | $0.0923 | $0.0053 |
| `claude-sonnet-5-5` | 0.288 | 173 (32%) | 0.98s | $0.2866 | $0.0164 |

\*At this project's real volume -- 31.0 new distinct descriptions/month on average, computed from
`gold.rpt_movements`'s real first-seen-month distribution (589 descriptions over 19 months), not
assumed.

**Cost and latency are not the deciding factor here -- quality is.** Both models are fractions of a
cent per call and sub-second; at this project's real volume the monthly bill is under two cents
either way. Both lose badly to the trained model on macro-F1 regardless: a general-purpose LLM
given only the 15 category *names*, with no examples of what each one means in this owner's own
labeling convention, cannot match a model trained directly on his 543 confirmed examples -- the
trained model has effectively seen the vocabulary ("PLAZA VEA", "UBER TRIP", abbreviations,
run-together Spanish-bank-statement text) this task actually needs; zero-shot Claude has not.

**Methodology note on Sonnet's 32% parse-failure rate** (so it is not misread as "Sonnet is worse
at this than Haiku," which the raw macro-F1 gap alone would suggest, though it is still well
behind the trained model either way): `claude-sonnet-5-5` defaults to adaptive thinking on, unlike
Haiku 4.5. At `max_tokens=30` -- sized for "one category name," not for a model that may also want
to think first -- a meaningful share of Sonnet's budget was consumed before any `text` content
block was emitted, producing an empty or cut-off reply this study counts as a failure (never
coerced into a guess, per `categorization/llm_classifier.parse_category`). A fairer Sonnet number
would need either a larger `max_tokens` (more cost, more latency, still unlikely to close a
~0.2 macro-F1 gap) or `thinking: {type: "disabled"}`/`between_tools` -- neither was worth the
extra spend once Haiku's own zero-shot number already settled the comparison. Reported as measured
either way, not re-run or adjusted after the fact.

## Alternatives not pursued (out of scope for this already-spent, approved budget)

- **Few-shot prompting** (a handful of the owner's own confirmed examples per category in the
  prompt, instead of just category names): the natural next lever if an LLM classifier were ever
  worth revisiting, and the likely reason zero-shot loses here -- not tried, since the trained
  model already answers "do we need an LLM for this" on cost/quality alone.
- **Disabling or budgeting Sonnet's thinking** to get a cleaner quality number: would cost more to
  find out something that would not change the verdict (Haiku's own zero-shot number already
  trails the trained model by the same margin that matters).

## Consequences

- No change to `categorization/model.py`, `scripts/categorize_new_movements.py`, or how a new
  movement gets its category (ADR 0045) -- the trained model keeps doing that job.
- `categorization/llm_classifier.py` and `scripts/claude_cost_study.py` stay in the repo as the
  reusable harness for a future, better-informed attempt (few-shot, a different model, a different
  task where an LLM's general knowledge matters more than this project's own narrow vocabulary) --
  not deleted, since the question is "not now," not "never," and re-running it costs cents.
- Real spend: $0.0923 + $0.2866 = **$0.3789** total for both models' full 543-call run (the first
  attempt failed before any billable call, on an empty Anthropic account balance the owner topped
  up before the real run) -- under the $0.49 estimate given before the run, since the actual
  per-call token counts ran a bit lower than the planning assumption.

## Related

[ADR 0044](0044-category-classifier-char-ngrams-vs-rules-baseline.md) (the trained model this
compares against), [ADR 0045](0045-batch-categorization-at-ingest.md) (how a new movement
actually gets categorized today), [ADR 0004](0004-real-pdfs-never-leave-your-machine.md)
(the "real text leaves the machine" bar this is the one deliberate exception to, with the owner's
own explicit sign-off).
