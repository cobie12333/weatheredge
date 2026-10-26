"""Minimal stdlib-only client for TypeSafe Jev (System One API)."""
from __future__ import annotations
import json, os, urllib.request
from typing import Any
API_URL=os.environ.get("TYPESAFE_API_URL","https://api.typesafe.ai/v1/systemone")
MODEL=os.environ.get("TYPESAFE_MODEL","jev-latest")
API_KEY=os.environ.get("TYPESAFE_API_KEY","")
TIMEOUT=float(os.environ.get("TYPESAFE_TIMEOUT_SECONDS","5"))
class JevError(RuntimeError): pass
def enabled()->bool: return bool(API_KEY)
def evaluate(state:dict[str,Any],questions:dict[str,dict[str,Any]])->dict[str,Any]:
    if not API_KEY: raise JevError("TYPESAFE_API_KEY is not configured")
    payload=json.dumps({"model":MODEL,"state":state,"questions":questions},separators=(",",":")).encode()
    req=urllib.request.Request(API_URL,data=payload,headers={"Authorization":f"Bearer {API_KEY}","Content-Type":"application/json","User-Agent":"weatheredge-jev/1.0"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=TIMEOUT) as response: return json.loads(response.read().decode())
    except Exception as exc: raise JevError(f"Jev request failed: {exc}") from exc
