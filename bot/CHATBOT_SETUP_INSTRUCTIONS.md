# Chatbot Setup — Instructions

## What this is (and isn't)
This is **not** a real AI model. Per the team's decision, the demo bot is **scripted**: it looks up a pre-written response from `data/test_cases.csv` based on which customer is asking and what they asked. This gives you full control over which failure modes appear in the demo, with zero risk of an LLM behaving unpredictably live on stage.

The gateway (built separately, not covered here) doesn't know or care whether the response came from a script or a real model — it only reads response text. That's the whole point: the gateway is bot-agnostic.

## File to create

```
rate-gateway/
└── src/
    └── bot.py
```

## Build `src/bot.py`

Ask Claude Code to write a small Python module with one main function:

```python
def get_bot_response(customer_id: str, customer_question: str) -> dict:
    """
    Looks up the matching row in data/test_cases.csv by customer_id + customer_question,
    and returns the pre-written bot_response along with its metadata.
    """
```

Requirements:
- Load `data/test_cases.csv` (once, at module import or via a simple cache — don't re-read the file on every call)
- Match on `customer_id` + `customer_question` (exact match is fine — these are your own scripted questions, not free text from a real user)
- Return a dict with: `bot_response`, `expected_gateway_action`, `scenario_type` (the last two are for your own reference/testing, not something the gateway itself should trust)
- If no match is found, return a clear error/None rather than guessing — this shouldn't happen if you're only calling it with your own test cases, but fail loudly if it does, so a typo doesn't silently break the demo

## Build a tiny CLI runner to sanity-check it (`src/run_bot.py`)

A simple script that:
1. Loops through every row in `test_cases.csv`
2. Calls `get_bot_response()` for each
3. Prints `customer_id`, `customer_question`, and the returned `bot_response` side by side

This is just to confirm the lookup works correctly for all ~22-24 test cases before wiring it into the gateway. It's not the final demo output — the final demo runner (built later, in the gateway phase) will show bot response → gateway check → corrected response together.

## Decisions already made (don't re-litigate mid-build)
- **Scripted, not live LLM**, for the primary demo — reliability over novelty
- The bot component's only job is to return text; it does zero verification itself — all correctness checking happens in the gateway (separate, later phase)
- If judges ask why it's scripted: the answer is "the gateway is model-agnostic — we scripted representative bot responses, including realistic hallucination patterns, to demonstrate full coverage of the gateway's logic in the time we had."

## Optional stretch (only if core demo is solid with time to spare)
Add a second function, `get_live_bot_response(customer_question: str) -> str`, that calls a real LLM API with a simple prompt (no context injection about correct rates — you want it free to hallucinate) and returns the raw response. Wire this in as an alternate path in the demo runner, not a replacement for the scripted path. Do not attempt this until the scripted path and the full gateway are working end-to-end.
