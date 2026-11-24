# LLM research: provider and model choice

**Prepared:** 2026-11-23 (updated 2026-11-24)
**Author:** Dipesh Kumar Panjiyar
**Project:** AI-Powered Website Link Analysis API

## 1. Requirements

The API must turn one public web page into five structured sections:

- competitor analysis (3+ competitors)
- at least 5 target search queries
- SEO improvements (keywords, title, meta, supporting content, fixes)
- at least 5 services
- target audience segments

That means the model needs:

1. reliable **JSON / structured output**;
2. enough output room for a verbose JSON object (about 2,500–4,000 tokens);
3. a context window large enough for a compact page extract (not the full page);
4. low latency for a live demo;
5. low cost per analysis;
6. a usable free tier or a cheap paid tier for the submission.

The API does **not** ask the model for search volumes or traffic estimates. Those
numbers cannot be produced responsibly without an official search-volume API.

## 2. Method

- List prices and context limits were taken from each provider's official pricing
  or model page on **2026-11-23**.
- Speed/TTFT figures from **Artificial Analysis** are included only where available
  and are explicitly marked as third-party measurements.
- A live Groq account was used for end-to-end tests of the actual prompt and JSON
  schema. The other providers were not live-tested because no API keys were
  available in this environment.
- The test page was `https://www.python.org/about/` (318 words extracted).
- The live model was `openai/gpt-oss-120b` on Groq, with `reasoning_effort=low`.

## 3. Comparison

Prices are USD per 1 million tokens. “Structured output” describes the strongest
JSON mode documented by the provider, not a guarantee of factual accuracy.

| Provider / model | Input $/1M | Output $/1M | Context | Structured output | Free tier / notes |
| --- | ---: | ---: | ---: | --- | --- |
| **Groq `openai/gpt-oss-120b`** | **0.15** | **0.60** | 131,072 | Strict JSON Schema | Free tier observed: 8,000 TPM, 1,000 requests/day |
| Groq `openai/gpt-oss-20b` | 0.075 | 0.30 | 131,072 | Strict JSON Schema | Same family; faster (~1,000 tok/s per Groq docs) |
| Groq `qwen/qwen3.8-27b` | 0.80 | 4.00 | 131,072 | JSON mode | Observed 1,000 output-token/min limit; not usable as fallback for this JSON size |
| Google Gemini 3.5 Flash-Lite | 0.30 | 2.50 | 1,048,576 | JSON schema | Free tier available; no key available to test |
| Google Gemini 3.8 Flash | 0.75 | 3.75 | 1,048,576 | JSON schema | Promo price through 2026-12-31 |
| Anthropic Claude Haiku 5.5 | 0.10 | 0.50 | 1,000,000 | JSON schema / tools | Strong low-cost quality option; no key available |
| Anthropic Claude Sonnet 5.5 | 2.00 | 10.00 | 1,000,000 | JSON schema / tools | Higher quality, much higher cost |
| OpenAI GPT-6 Luna | 0.10 | 0.50 | 1,050,000 | Structured Outputs | Very strong price/context; no key available |
| OpenAI GPT-6.1 Terra | 1.00 | 5.00 | 1,050,000 | Structured Outputs | Higher-cost quality option |
| DeepSeek Flash | 0.15 / 0.30* | 0.60 / 1.20* | 1,000,000 | JSON mode | *Off-peak / peak pricing; no key available |
| DeepSeek V4 Pro | 0.66* | 1.98* | 1,000,000 | JSON mode | *Off-peak; higher quality tier |
| OpenRouter `z-ai/glm-5.3-flash` | 0.0399 | 0.0784 | Model-dependent | JSON mode | Cheapest listed option; routing/availability risk |

### Third-party speed measurements (Artificial Analysis)

These are **not** measurements of this API. They are useful signals only:

| Model | Output speed | Time to first token | Notes |
| --- | ---: | ---: | --- |
| Gemini 3.5 Flash-Lite | ~310 tok/s | 4.54 s | Measured by Artificial Analysis |
| Claude Haiku 5.5 | ~220 tok/s | 9.31 s | Medium reasoning |
| GPT-6 Luna | 93–94 tok/s | 2.49 s low / 1.41 s non-reasoning | Measured by Artificial Analysis |
| DeepSeek Flash | 167–170 tok/s | 0.96 s non-reasoning | Measured by Artificial Analysis |

Groq's own model page lists `gpt-oss-120b` at roughly **500 output tok/s** and
`gpt-oss-20b` at roughly **1,000 output tok/s**. Our live end-to-end run produced
3,093 output tokens in 7.5 seconds of LLM time (~412 tok/s effective, including
queueing and network overhead).

## 4. Live Groq verification

### Small structured-output test

The first test used the same JSON schema with a short prompt:

- model: `openai/gpt-oss-120b`
- `reasoning_effort=low`
- result: valid structured JSON in **1.20 s**
- usage: 234 prompt tokens / 217 completion tokens (104 reasoning tokens)

This confirmed that the Groq account supports strict JSON Schema and that the
schema was accepted.

### Full API run

| Metric | Observed |
| --- | ---: |
| Page | `https://www.python.org/about/` |
| Extracted words | 318 |
| Input tokens | 3,495 |
| Output tokens | 3,093 |
| Total tokens | 6,588 |
| Estimated cost | **$0.00238005** |
| LLM latency | 7,503 ms |
| End-to-end request | 8.18 s |
| Repair attempts | 0 |
| Fallback used | No |

At this rate, 1,000 analyses cost roughly **$2.38** at list price. The free tier is
sufficient for a demo, but the account's observed **8,000 tokens/minute** limit is
tight for long pages or repair attempts.

### Failure found during testing

With `MAX_INPUT_CHARS=8500` and `LLM_MAX_OUTPUT_TOKENS=4000`, Groq rejected a
request with HTTP 413:

> Request too large ... on tokens per minute (TPM): Limit 8000, Requested 8795

A request counts **prompt tokens + `max_tokens`**, so the configured output cap
matters even if the model would stop earlier. The production defaults were reduced
to:

- `MAX_INPUT_CHARS=6500`
- `LLM_MAX_OUTPUT_TOKENS=3500`

A subsequent run used 3,495 input + 3,093 output = 6,588 tokens and succeeded on
the primary model with no fallback.

The original fallback was `qwen/qwen3.8-27b`, but Groq returned HTTP 429 for that
model because its observed output-token-per-minute limit was 1,000 while the
request asked for 3,500 output tokens. The fallback was changed to
`openai/gpt-oss-20b`, which uses the same structured-output family and has its own
token budget.

## 5. Token budget

The budget is deliberately conservative for the free Groq tier:

| Component | Approximate tokens |
| --- | ---: |
| Page context (`MAX_INPUT_CHARS=6500`) | 2,000–2,500 |
| System prompt + JSON schema | 1,000–1,500 |
| `max_tokens` output cap | 3,500 |
| **Worst-case request** | **~7,000–7,500** |

The observed request was 6,588 tokens, leaving some headroom. Increasing either
limit without upgrading the Groq tier will cause 429/413 responses on long pages.

## 6. Recommendation

**Primary:** Groq `openai/gpt-oss-120b`

- cheapest verified option per analysis for this workload ($0.15/$0.60);
- strict JSON Schema support;
- 131k context is more than enough for the compact page evidence bundle;
- fast and free-tier accessible;
- actual output was valid and required no repair.

**Fallback:** Groq `openai/gpt-oss-20b`

- same structured-output family;
- cheaper and faster;
- avoids the Qwen output-token-per-minute wall observed during testing.

**Production alternative if a key is available:** Google Gemini 3.5 Flash-Lite.
It has a 1M context window, JSON schema support and a lower output price than
`gpt-oss-120b` at $0.30 input / $2.50 output. For this workload the output cost
dominates, so the Groq model remains cheaper, but Gemini is a strong second
provider for redundancy.

**Not selected for this submission:** Claude Haiku 5.5 and GPT-6 Luna are
excellent on paper ($0.10/$0.50 and $0.10/$0.50), but neither had an available key
for live verification. They are implemented as adapters and can be enabled with
`LLM_PROVIDER=anthropic` or `LLM_PROVIDER=openai`.

## 7. Sources

Official pricing / model pages (checked 2026-11-23):

- Groq models and prices: https://console.groq.com/docs/models
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq structured outputs: https://console.groq.com/docs/structured-outputs
- Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Anthropic pricing: https://www.anthropic.com/pricing
- OpenAI API pricing: https://openai.com/api/pricing/
- DeepSeek pricing: https://api-docs.deepseek.com/quick_start/pricing
- OpenRouter models: https://openrouter.ai/models
- Artificial Analysis: https://artificialanalysis.ai/

Provider prices and rate limits change frequently. Re-check them before relying on
the cost figures or free-tier assumptions in production.

## 8. Limitations

- Only the Groq path was live-tested; the Gemini/Anthropic/OpenAI/DeepSeek
  adapters are implemented but need provider-specific smoke tests.
- Artificial Analysis speed numbers are third-party benchmarks, not guarantees.
- Free-tier limits can change without notice; the observed 8,000 TPM limit is the
  key operational constraint for this submission.
- Model output is not fact-checked. Competitor names, comparisons and SEO
  opportunities are suggestions and are labelled accordingly in the API response.
- No search-volume data is generated or claimed.