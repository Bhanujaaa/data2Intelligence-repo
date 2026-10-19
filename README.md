# Data2Intelligence — a trust layer for banking chatbots

A verification gateway that sits between an AI chatbot and the customer. The
chatbot's answer is generated live by an LLM; before the customer sees it, the
gateway checks every rate and fee against the bank's own data and returns
**PASS**, **CORRECT** (the wrong number is swapped for the right one) or
**FALLBACK** (a safe message and a human hand-off). Every verdict carries the
exact data rows behind it, four trust signals and an audit record.

> **AI reads. Rules decide. The data explains why.**

Built at a hackathon for a fictional bank, **FirstVault**. All data is made up.

---

## How it works

```
Customer question
      │
      ▼
 mask PII ──► LLM chatbot (Groq) ──► answer text          ← never scripted
                                         │
                                         ▼
                    Gateway ─ 1. LLM reads: extract each rate/fee claim as JSON   (Groq)
                            ─ 2. Rules decide: verify.py vs golden_dataset/        (no LLM)
                            ─ 3. Trust signals: provenance, reliability,
                                 freshness, cross-source agreement                 (no LLM)
                            ─ 4. Verdict: PASS / CORRECT / FALLBACK
                            ─ 5. Audit log + lineage
                                         │
                                         ▼
                              Customer sees the verified answer
```

| Step | Uses an LLM? | Why |
|---|---|---|
| Chatbot answer | Yes (Groq) | It's an ordinary chatbot. It knows product names and the signed-in customer's own accounts, **not** the rate sheet — so it can be wrong, like real bots |
| Extract claims | Yes (Groq) | Reads natural phrasing ("just over nine percent", "my loan") into structured JSON |
| Verify | **No** | Compliance-critical comparison against the golden dataset, with fixed tolerances |
| Trust signals | **No** | Computed from data: which rows, which tier, how fresh, which sources disagree |
| Decide + log | **No** | Fixed rules; fail closed |

### Verdicts
| Verdict | When | Customer sees |
|---|---|---|
| PASS | the figure matches the rule for this customer | the answer as written |
| CORRECT | wrong tier, stale rate, APR/APY mix-up, closed account — right value known | the answer with the number replaced |
| FALLBACK | unknown product, ambiguous "my loan", low-confidence match, LLM failure, expired pricing rule | a safe "let me confirm" message; flagged for human review |

### Trust signals (`gateway/trust_signals.py`)
| Signal | Question | Computed from |
|---|---|---|
| Provenance | Can we trace it back? | the golden-dataset rows each verdict used |
| Source reliability | How authoritative is it? | `golden_dataset/source_registry.csv` tiers |
| Freshness | Is it still valid? | newest `effective_date` wins; pricing rules past their shelf life → FALLBACK |
| Cross-source agreement | Do sources agree? | `secondary_sources/` (branch FAQ, marketing page) vs the system of record |

Personal data (card, PAN, Aadhaar, SSN, email, phone) is masked before any LLM
call, log or API response (`gateway/pii.py`). Customer names are never sent to the LLM.

---

## Project structure

```
data2intelligence/
├── bot/
│   ├── bot.py               # LLM chatbot (Groq) — every answer generated live
│   ├── api.py               # FastAPI: /chat, /verify, /customers, /sample-questions, /health
│   └── run_bot.py           # ask the LLM all sample questions -> bot/output/responses.json
├── gateway/
│   ├── extract_and_match.py # LLM step: claims -> JSON
│   ├── verify.py            # rule step: no LLM
│   ├── trust_signals.py     # provenance, reliability, freshness, agreement
│   ├── pii.py               # PII masking
│   ├── gateway.py           # orchestrator; --batch verifies bot/output/responses.json
│   ├── demo.py              # terminal demo: ask the LLM, then verify
│   └── legacy_regex/        # first hackathon version (regex), not used
├── golden_dataset/          # the bank's source of truth (system of record)
│   ├── products.csv  pricing_rules.csv  customers.csv  accounts.csv
│   ├── source_registry.csv  # tier, shelf life and owner of every source
│   └── sample_questions.csv # example questions for the UI — questions only
├── secondary_sources/       # lower-tier sources that can disagree (branch FAQ, marketing page)
├── ui/index.html            # chat UI (React, no build step)
├── tests/
│   ├── fixtures/gateway_test_cases.csv  # hand-written bad answers, used ONLY to test the rules offline
│   ├── test_gateway_offline.py
│   └── test_bot_llm.py
├── fake_data/generate_data.py           # regenerates the fictional dataset
├── aws/handler.py  template.yaml        # AWS Lambda deploy (see AWS_DEPLOY.md)
└── requirements.txt  requirements-dev.txt  .env.example
```

There are no scripted chatbot answers anywhere in the app. The only hand-written
answers are the test fixtures, which feed the gateway known-bad replies so the
rules can be tested offline without an API key.

---

## Run locally

Needs **Python 3.10+** (3.12 recommended — it matches AWS Lambda) and a Groq API key.

```bash
python3.12 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env                   # then paste your GROQ_API_KEY
python -m pytest -q                    # offline tests, no key needed

uvicorn bot.api:app --reload           # API on http://localhost:8000
open ui/index.html                     # chat UI (in a second terminal)
```

In the UI, pick a customer (or General), type a question or click a suggestion,
and open **▸ Details** under the answer for the reliability score, references,
trust signals and lineage.

### Terminal tools
```bash
python gateway/demo.py --customer CUST003 "What APR would I get on a Personal Loan?"
python bot/run_bot.py --delay 4        # ask the LLM all sample questions
python gateway/gateway.py --batch      # verify those live answers
```
The Groq free plan is rate-limited; keep a few seconds between calls. If a call
fails, the gateway returns FALLBACK — it never passes an unverified answer.

### Try these
| Customer | Question | What to look for |
|---|---|---|
| Sofia Reyes (680) | What APR would I get on a Personal Loan? | her tier is 14.99%; a best-tier 6.99% gets CORRECTed |
| General | What APY does the High-Yield Savings offer for balances over $10,000? | live rate 4.20%; the branch FAQ's old 4.50% is shown as outranked |
| Hannah Johansson | What's the current rate on my loan? | she has two loans → FALLBACK |
| General | What is the rate on your Money Market account? | not a FirstVault product → FALLBACK |
| General | (any question containing a card number) | the number is masked before the LLM |

Because the chatbot is a live model, its answer — and so the verdict — can
differ between runs. That's the point: the gateway checks whatever it says.

---

## Deploy to AWS (free-tier friendly)

One Lambda (FastAPI via Mangum) behind a Lambda function URL, a DynamoDB audit
table, and the Groq key in SSM Parameter Store. No Bedrock, no API Gateway.
Steps in **[AWS_DEPLOY.md](AWS_DEPLOY.md)**.

---

## Security
- Never commit `.env` (it's in `.gitignore`). Rotate any key that was ever committed.
- The demo function URL is public — delete the stack (`sam delete`) after use.
- Demo code with fictional data — not production banking software.
