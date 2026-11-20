"""Structured output through OpenAI-compatible Chat Completions endpoints."""
import os
from fnmatch import fnmatchcase


def _strict_schema(fmt):
    """JSON Schema for a pydantic model, closed for strict structured outputs."""
    schema = fmt.model_json_schema()

    def close(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(schema)
    return schema


def _json_text(content):
    """Pull the JSON object out of a chat message's content."""
    if isinstance(content, list):  # content parts
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "") or ""
            for part in content
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("model returned no text content")
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"model returned no JSON object: {content[:200]!r}")
    return content[start:end + 1]  # tolerates code fences around the object


def response_format(fmt, strict=True):
    return {"type": "json_schema", "json_schema": {
        "name": fmt.__name__, "strict": strict, "schema": _strict_schema(fmt)}}


def _header_patterns(variable, default=""):
    return tuple(item.strip().lower() for item in os.getenv(variable, default).split(",")
                 if item.strip())


def _check_choice(refusal, finish_reason):
    if refusal:
        raise RuntimeError("The model refused the structured output request")
    if finish_reason not in (None, "stop"):
        raise RuntimeError(f"Incomplete Chat Completion (finish_reason={finish_reason})")


def _read_content(response, stream):
    if stream:
        parts = []
        finished = False
        with response:
            for chunk in response:
                if getattr(chunk, "error", None):
                    raise RuntimeError("Gateway reported an error during streaming")
                for choice in chunk.choices or ():
                    if choice.index == 0:
                        _check_choice(choice.delta.refusal, choice.finish_reason)
                        parts.append(choice.delta.content or "")
                        finished |= choice.finish_reason == "stop"
        if not finished:
            raise RuntimeError("Chat Completion stream ended before a stop event")
        return "".join(parts)
    if not response.choices:
        raise RuntimeError("Chat Completion returned no choices")
    choice = response.choices[0]
    _check_choice(choice.message.refusal, choice.finish_reason)
    if choice.finish_reason is None:
        raise RuntimeError("Chat Completion ended without a finish reason")
    return choice.message.content


class ChatCompletionsWrapper:
    def __init__(self, model, base_url=None, api_key=None, stream=False, temperature=None,
                 metadata_callback=None):
        from openai import OpenAI
        self.model = model
        endpoint = base_url or os.getenv("OPENAI_BASE_URL")
        if not endpoint:
            raise ValueError("Set OPENAI_BASE_URL or pass base_url for Chat Completions")
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("Set OPENAI_API_KEY or pass api_key for Chat Completions")
        self.client = OpenAI(base_url=endpoint, api_key=key, timeout=60, max_retries=0)
        self.is_openrouter = endpoint.rstrip("/") == "https://openrouter.ai/api/v1"
        self.temperature = temperature
        self.stream = stream
        self.metadata_callback = metadata_callback
        self.cost_headers = _header_patterns("NL2LOGIC_COST_HEADERS")
        self.trace_headers = _header_patterns("NL2LOGIC_TRACE_HEADERS", "x-request-id,x-trace-id")

    def _metadata(self, headers, fmt, attempt):
        trace = next((headers[name] for name in self.trace_headers if headers.get(name)), None)
        if self.metadata_callback:
            selected = {k: v for k, v in headers.items()
                        if any(fnmatchcase(k.lower(), pattern) for pattern in self.cost_headers)}
            self.metadata_callback({"model": self.model, "schema": fmt.__name__,
                                    "attempt": attempt, "trace_id": trace, "headers": selected})
        return trace

    def generate(self, text, fmt):
        from openai import APIStatusError
        request = dict(model=self.model, messages=[{"role": "user", "content": text}],
                       response_format=response_format(fmt), stream=self.stream)
        if self.is_openrouter:
            request["extra_body"] = {"provider": {"require_parameters": True}}
        if self.temperature is not None:
            request["temperature"] = self.temperature
        for attempt in (1, 2):
            try:
                raw = self.client.chat.completions.with_raw_response.create(**request)
            except APIStatusError as exc:
                trace = self._metadata(exc.response.headers, fmt, attempt)
                suffix = f" (trace ID {trace})" if trace else ""
                raise RuntimeError(f"Chat Completions HTTP {exc.status_code}{suffix}: {exc.message}") from exc
            try:
                self._metadata(raw.headers, fmt, attempt)
                content = _read_content(raw.parse(), self.stream)
            finally:
                raw.http_response.close()
            try:
                return fmt.model_validate_json(_json_text(content))
            except ValueError as exc:
                if attempt == 2:
                    raise ValueError(f"Invalid {fmt.__name__} JSON after two attempts: {exc}") from exc

    def close(self):
        self.client.close()
