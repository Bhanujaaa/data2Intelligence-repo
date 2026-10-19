# Data2Intelligence on AWS (free-tier friendly)

The LLM chatbot and the verification gateway — Groq reads, rules decide — with
trust signals and a one-command AWS deploy. **No Amazon Bedrock, no API Gateway.**

```
ui/index.html ──► Lambda function URL ──► AWS Lambda (FastAPI via Mangum)
                                              │
  mask PII ─► Groq chatbot answer ─► Groq extract+match ─► verify.py rules ─► trust signals
                                              │                       │
                                   golden_dataset/*.csv     secondary_sources/*.csv
                                              │
                                   PASS / CORRECT / FALLBACK ─► DynamoDB audit + CSV
```

| Piece | Service | Cost note |
|---|---|---|
| Compute | AWS Lambda | free tier: 1M requests + 400,000 GB-s / month |
| HTTPS endpoint | Lambda function URL | included in Lambda request/duration pricing |
| Audit trail | DynamoDB, provisioned 5 RCU / 5 WCU | free tier: 25 RCU, 25 WCU, 25 GB |
| Groq key | SSM Parameter Store (standard SecureString) | standard parameters: no additional charge |
| LLM | Groq (`openai/gpt-oss-20b` by default) — 2 calls per message (answer + extraction) | Groq free plan, rate-limited |

New AWS accounts use a credit-based free plan — check your own account's terms and
set a billing alarm.

## What changed from the hackathon code
| File | Change |
|---|---|
| `gateway/pii.py` (new) | masks card, PAN, Aadhaar, SSN, email, phone before Groq, logs and API response |
| `gateway/trust_signals.py` (new) | provenance, source reliability, freshness, cross-source agreement; freshness gate |
| `golden_dataset/source_registry.csv` (new) | tier, data type, shelf life and owner for every source |
| `secondary_sources/*.csv` (new) | a stale branch FAQ and a marketing page, to show conflicts |
| `gateway/verify.py` | **bug fix:** general questions now use the balance / credit score in the conversation; before, a stale 4.50% was "corrected" to 3.80% instead of 4.20% |
| `gateway/gateway.py` | PII masking, trust signals, freshness gate, DynamoDB audit, writable dir via env |
| `chatbot/assistant.py`, `api/main.py` | chatbot answers come from the LLM; PII masked; no names sent; `/sample-questions` replaces `/test-cases` |
| `tests/fixtures/gateway_test_cases.csv` | known-bad answers used to test the rules offline |
| `ui/index.html` | question suggestions; API URL from `?api=`; shows trust signals and conflicts |
| `aws/handler.py`, `template.yaml` | Lambda entry point (Mangum) and SAM template |
| `tests/` | 13 offline tests (gateway rules with fixtures; chatbot with a mocked LLM) |

## Run locally
See README.md › Run locally.

## Deploy to AWS
```bash
aws ssm put-parameter --name /data2intelligence/groq-api-key \
    --type SecureString --value "<NEW_GROQ_KEY>"
sam build
sam deploy --guided             # note the ApiUrl output
open "ui/index.html?api=<ApiUrl without trailing slash>"
```
To verify a batch of answers locally (spacing calls for the Groq free plan):
```bash
python scripts/run_sample_questions.py --delay 4
python gateway/gateway.py --batch
```

## After the talk
- Delete the stack (`sam delete`) or set the function URL to `AWS_IAM`
- Never commit `.env`; rotate any key that was ever committed
