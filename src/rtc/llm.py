"""Provider-neutral LLM client with structured output, native tool calling and a disk cache.

    client = make_client("databricks-qwen35-122b-a10b")
    r = client.complete(messages, schema=Router, cache_key="router@1")          # structured
    r = client.complete(messages, tools=specs, cache_key="tools@1")             # tool calling

Every Response carries provider, model, tokens, latency and how structured output was obtained.
The model name comes from config, never from the code that uses the client. Adapted from the
macro-sql-br client (same cache layout and backoff).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ValidationError


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[dict] | None = None  # assistant turn that called tools (provider format)
    tool_call_id: str | None = None  # tool turn


class Response(BaseModel):
    text: str = ""
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    tool_calls: list[ToolCall] = []
    raw_tool_calls: list[dict] | None = None  # to echo back in the assistant turn
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int
    structured_mode: Literal["constrained", "prompted", "none"] = "none"
    cached: bool = False


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(
        self,
        messages: list[Message],
        schema: type[BaseModel] | None = None,
        tools: list[dict] | None = None,
        cache_key: str | None = None,
    ) -> Response: ...


def _strip(node: Any) -> Any:
    """Pydantic/MCP schemas carry `title` and `format`; some grammar engines reject them
    (Gemma rejects `format: date`, found in both spikes)."""
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("title", "format")}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def json_schema(model: type[BaseModel]) -> dict:
    s = _strip(model.model_json_schema())
    s["additionalProperties"] = False
    return s


def tool_spec(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": _strip(parameters)},
    }


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text: str, schema: type[BaseModel]) -> tuple[dict | None, str | None]:
    m = _JSON_BLOCK.search(text or "")
    if not m:
        return None, "no JSON object in output"
    try:
        return schema.model_validate_json(m.group(0)).model_dump(mode="json"), None
    except ValidationError as e:
        return None, f"schema: {e.errors()[0]['msg']}"[:300]


def _dump(messages: list[Message]) -> list[dict]:
    return [m.model_dump(exclude_none=True) for m in messages]


class DatabricksClient:
    """Databricks Model Serving (Free Edition foundation models), OpenAI-style chat payload."""

    provider = "databricks"

    def __init__(self, model: str, timeout: float = 180, max_tokens: int = 2000):
        from databricks.sdk import WorkspaceClient

        self.model = model
        self._w = WorkspaceClient()
        self._http = httpx.Client(timeout=timeout)
        self._max_tokens = max_tokens

    def _post(self, payload: dict, max_retries: int = 6) -> httpx.Response:
        url = f"{self._w.config.host}/serving-endpoints/{self.model}/invocations"
        for attempt in range(max_retries + 1):
            try:
                resp = self._http.post(url, headers=self._w.config.authenticate(), json=payload)
            except httpx.TransportError:
                if attempt == max_retries:
                    raise
                time.sleep(min(2 ** (attempt + 1), 60))
                continue
            if resp.status_code != 429 and resp.status_code < 500:
                return resp
            if attempt == max_retries:
                return resp
            ra = resp.headers.get("retry-after")
            time.sleep(min(float(ra) if ra and ra.isdigit() else 2 ** (attempt + 1), 60))
        return resp

    def complete(self, messages, schema=None, tools=None, cache_key=None) -> Response:
        payload: dict[str, Any] = {
            "messages": _dump(messages),
            "temperature": 0,
            "max_tokens": self._max_tokens,
        }
        mode: Literal["constrained", "prompted", "none"] = "none"
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if schema is not None:
            mode = "constrained"
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema(schema),
                    "strict": True,
                },
            }
        t0 = time.perf_counter()
        resp = self._post(payload)
        if schema is not None and resp.status_code == 400:
            mode = "prompted"
            payload.pop("response_format")
            hint = "\n\nAnswer with a single JSON object only, matching this JSON schema:\n"
            payload["messages"][0]["content"] += hint + json.dumps(json_schema(schema))
            resp = self._post(payload)
        latency = int((time.perf_counter() - t0) * 1000)
        resp.raise_for_status()
        body = resp.json()
        msg = body["choices"][0]["message"]
        content = msg.get("content") or ""
        if isinstance(content, list):  # reasoning models return typed parts
            content = "".join(p.get("text", "") for p in content if p.get("type") == "text")
        raw_calls = msg.get("tool_calls") or []
        calls = []
        for c in raw_calls:
            args = c["function"].get("arguments") or "{}"
            try:
                parsed_args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                parsed_args = {"_unparseable": args}
            calls.append(
                ToolCall(id=c.get("id", ""), name=c["function"]["name"], arguments=parsed_args)
            )
        usage = body.get("usage") or {}
        out = Response(
            text=content,
            tool_calls=calls,
            raw_tool_calls=raw_calls or None,
            provider=self.provider,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=latency,
            structured_mode=mode,
        )
        if schema is not None:
            out.parsed, out.parse_error = parse_json(content, schema)
        return out


class CachedClient:
    """Disk cache keyed by (cache_key = prompt version, provider, model, hash of the input)."""

    def __init__(self, inner: LLMClient, directory: Path):
        self.inner = inner
        self.provider, self.model = inner.provider, inner.model
        self.dir = directory

    def _path(self, messages, schema, tools, cache_key) -> Path:
        blob = json.dumps(
            {
                "k": cache_key,
                "p": self.provider,
                "m": self.model,
                "msgs": _dump(messages),
                "schema": json_schema(schema) if schema else None,
                "tools": tools,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return self.dir / f"{hashlib.sha256(blob.encode()).hexdigest()}.json"

    def complete(self, messages, schema=None, tools=None, cache_key=None) -> Response:
        path = self._path(messages, schema, tools, cache_key)
        if path.exists():
            r = Response.model_validate_json(path.read_text(encoding="utf-8"))
            return r.model_copy(update={"cached": True})
        resp = self.inner.complete(messages, schema=schema, tools=tools, cache_key=cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.model_dump_json(), encoding="utf-8")
        return resp


CACHE_DIR = Path(
    os.environ.get("RTC_LLM_CACHE", Path(__file__).resolve().parents[2] / ".cache" / "llm")
)


def make_client(model: str, cache: bool = True) -> LLMClient:
    """`model` is a Databricks serving endpoint name; other providers plug in here."""
    client: LLMClient = DatabricksClient(model)
    return CachedClient(client, CACHE_DIR) if cache else client
