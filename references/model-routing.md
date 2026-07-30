# Model routing

Which model for which job. Read this before wiring an AI call into a script, an
admin route, or an agent.

The principle behind it: we do not own the models and cannot count on any tier
staying available or staying priced the same. What we own is the process. Put the
judgment in the prompt and the skill, then run it on the cheapest model that
holds quality. See `.claude/skills/fable-mode/SKILL.md` (global) for the method
half of this, and `decisions/log.md` (2026-07-30) for the decision.

## Provider split

This is settled and not a per-task judgment call.

- **Claude** for dev and admin tooling. Code, QC, agents, content pipelines,
  anything internal.
- **Gemini** for student-facing features and **all** image generation. Cost at
  student volume, and the platform is already on Google infrastructure.

Never route a student-facing feature to Claude to "improve quality." That is a
cost decision that belongs to Shane, not to a session.

## The Claude table

Prices are per million tokens, input / output, from the Anthropic API reference
(cached 2026-06-24). Cost score is ours: higher is cheaper.

| Model | ID | Cost | Intelligence | Taste | Context |
|---|---|---|---|---|---|
| Haiku 4.5 | `claude-haiku-4-5` | 5 ($1 / $5) | 2 | 1 | 200K |
| Sonnet 5 | `claude-sonnet-5` | 4 ($3 / $15) | 4 | 3 | 1M |
| Opus 5 | `claude-opus-5` | 2 ($5 / $25) | 5 | 5 | 1M |
| Fable 5 | `claude-fable-5` | 1 ($10 / $50) | 5 | 5 | 1M |

Sonnet 5 is at an introductory $2 / $10 through **2026-08-31**. That is two weeks
past launch, so do not build a budget on it.

**Intelligence** is how well it holds a hard problem: debugging, reviewing code,
multi-step work where the first idea is wrong. **Taste** is judgment calls with no
right answer: curriculum voice, UI, deciding what a lesson should feel like.

## Reach for this when

| Job | Model | Why |
|---|---|---|
| Bulk classification, tagging, extraction | **Haiku 4.5** | No judgment needed. The volume is the cost. |
| Scout and worker agents under an orchestrator | **Haiku 4.5** | Measured ~3x cheaper at the same output. See below. |
| Bulk content passes across many lessons | **Sonnet 5** | Needs to hold voice across a long run. |
| Drafting curriculum prose for Shane to edit | **Sonnet 5** | Taste matters, but it gets human review. |
| Platform work in `D:\GK12-Platform` | **Opus 5** | Firestore, auth, deploys. Wrong is expensive. |
| Debugging anything | **Opus 5** | The whole job is the first theory being wrong. |
| Orchestrating a multi-agent run | **Opus 5** | Planning is where intelligence pays. |
| Anything touching prod data | **Opus 5** | Not reversible. |
| Student-facing generation | **Gemini 2.5 Flash** | Provider split. |
| Every image | **Imagen 4 Fast** | Provider split. `imagen-4.0-fast-generate-001` with `:predict`. |

**Fable 5 is not in our rotation.** It costs double Opus 5, requires 30-day data
retention, and nothing we do has been blocked by Opus 5 being insufficient. Revisit
only if a specific job actually fails on Opus.

## The orchestrator pattern

For multi-agent work, a strong orchestrator delegating to cheap workers beats
same-model-throughout. Nate Herk measured an Opus orchestrator with Haiku scouts at
roughly 3x cheaper than Opus-with-Opus at the same output quality.

**Not verified on our workloads.** Treat the 3x as his number until we measure a
real pipeline run.

The reason it works: the orchestrator does the planning, the adversarial pass, and
the verification. Workers execute a scoped instruction and report back. Execution
does not need the expensive model. Planning does.

## Effort, not just model

Both Opus 5 and Sonnet 5 take `output_config: {effort: ...}`, from `low` to `max`.
Default is `high`.

- **`low` / `medium`** for subagents and scoped work. Genuinely strong on Opus 5.
- **`high`** is the sensible default.
- **`xhigh`** for hard coding and agentic runs.
- **`max`** only when correctness beats cost.

Higher is not automatically better. Above `xhigh` the model can overthink, second
guess, and produce worse output for more money. Sweep the levels on a real task
rather than reaching for `max`.

## Gemini model IDs

Probed live against the API on 2026-07-30. All four return 200:

- `gemini-2.5-flash` for text. 1M in / 65K out.
- `gemini-2.5-flash-lite` is **live and current**, same 1M / 65K limits, and
  roughly 3-6x cheaper. It is the tutor cost lever in `references/platform-costs.md`.
  The deprecated id is the older **`gemini-2.5-flash-lite-preview`**, not this one.
  Do not confuse the two.
- `gemini-2.5-pro` where flash is not enough. 1M / 65K.
- `gemini-2.5-flash-image` for image understanding. 32K / 32K.
- `imagen-4.0-fast-generate-001` for generation, called with `:predict`.
- Set `thinkingBudget: 0` for short JSON responses, or thinking tokens truncate
  the output.

The 3.x line also answers on our key: `gemini-3.1-flash-lite` and
`gemini-3.1-flash-image` both round-trip clean. **`gemini-3.5-flash` returned a 503
"experiencing high demand"** on 2026-07-30. The id is valid but capacity is not
guaranteed, so do not point an unattended pipeline at it without a fallback.

Verify a model with a real `generateContent` round-trip, not a `models.get`. A 200
from `models.get` only proves the id resolves.

## When switching a model

- Model IDs are exact strings. Never append a date suffix to an alias.
- `budget_tokens` is dead on every current model. Use `effort`.
- `temperature`, `top_p`, and `top_k` are rejected on Opus 5 and Sonnet 5. Steer
  with the prompt instead.
- Changing the model invalidates the prompt cache. The first call after a swap
  pays a cold write.
