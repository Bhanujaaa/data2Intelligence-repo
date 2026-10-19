"""
AWS Lambda entry point — runs the existing FastAPI app (bot/api.py) unchanged.
==============================================================================
Lambda function URL  ->  Mangum  ->  FastAPI routes (/chat, /verify, /customers, ...)

Cold start:
  1. Read the Groq API key from SSM Parameter Store (SecureString) into the
     environment BEFORE the gateway is imported (extract_and_match reads it at import).
  2. Point writable folders at /tmp (the only writable path on Lambda).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GATEWAY_WRITE_DIR", "/tmp/gateway")
os.environ.setdefault("BOT_WRITE_DIR", "/tmp/bot")

_param = os.environ.get("GROQ_KEY_PARAM")
if _param and not os.environ.get("GROQ_API_KEY"):
    import boto3
    os.environ["GROQ_API_KEY"] = boto3.client("ssm").get_parameter(
        Name=_param, WithDecryption=True)["Parameter"]["Value"]

from mangum import Mangum          # noqa: E402
from bot.api import app            # noqa: E402

handler = Mangum(app, lifespan="off")
