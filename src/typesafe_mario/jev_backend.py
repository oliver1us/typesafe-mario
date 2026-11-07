"""Backend-agnostic Jev transport.

Upstream talks to TypeSafe through typesafe_sdk.TypeSafeClient, hardwired to
https://api.typesafe.ai. This module offers a drop-in client with the same
system_one(state=..., questions=...) surface for System One-compatible endpoints.

Providers
---------
direct      https://api.typesafe.ai/v1/systemone    (TYPESAFE_API_KEY)
openrouter  https://openrouter.ai/api/v1/systemone (OPENROUTER_API_KEY)
ollama      http://localhost:11434/v1/systemone     (no key, local weights)

The local route requires a server exposing /v1/systemone; standard Ollama chat
endpoints are not interchangeable with this protocol. We normalize compatible
responses at the edge.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "JevBackend",
    "MultiBackendClient",
    "SystemOneError",
    "SystemOneResponse",
    "Usage",
]

DEFAULT_TIMEOUT = 30.0

ENDPOINTS = {
    "direct": "https://api.typesafe.ai/v1/systemone",
    "openrouter": "https://openrouter.ai/api/v1/systemone",
    "ollama": "http://localhost:11434/v1/systemone",
}

# Per-backend model id. The harness is calibrated against Jev 1.13, so every
# backend is asked for that exact build where the name differs.
MODELS = {
    "direct": "jev-latest",
    "openrouter": "typesafe/jev-1.13",
    "ollama": "nimble",  # Configured local default; availability depends on the server.
}

KEY_ENV = {
    "direct": "TYPESAFE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",  # usually unset; Ollama local needs no auth
}


class SystemOneError(RuntimeError):
    """Raised when a backend rejects or fails a System One call."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None

    @property
    def cost_per_call(self) -> float:
        """Cost of this call in USD, derived when the backend omits it."""
        if self.cost is not None:
            return self.cost
        return (self.input_tokens / 1_000_000) * 0.042


@dataclass(frozen=True)
class Answer:
    """One question's answer, normalized across backends.

    Backends disagree on where the value lives: TypeSafe's SDK groups them
    under choices/nouls/scores, raw HTTP nests everything under answers.
    Both are flattened to this shape by _extract.
    """

    question_id: str
    type: str
    choice: str | None = None
    noul: float | None = None
    score: Any | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


class SystemOneResponse:
    """Minimal duck-type of the SDK response that TypeSafePolicy needs.

    The policy layer reads response.choices[q], response.nouls[q] and
    response.scores[q] (see TypeSafePolicy._answer), so exposing those three
    mappings satisfies it without a hard SDK dependency.
    """

    def __init__(self, answers, usage, *, model, backend, latency_ms) -> None:
        self.answers = dict(answers)
        self.model = model
        self.backend = backend
        self.latency_ms = latency_ms
        self.usage = usage
        self.input_tokens = usage.input_tokens
        self.output_tokens = usage.output_tokens
        self.cost = usage.cost_per_call

        self.choices = {q: a for q, a in answers.items() if a.choice is not None}
        self.nouls = {q: a for q, a in answers.items() if a.noul is not None}
        self.scores = {q: a for q, a in answers.items() if a.score is not None}


def _answer_from_raw(question_id: str, raw: Any) -> Answer:
    """Normalize one raw answer object across backends."""
    if not isinstance(raw, dict):
        return Answer(question_id=question_id, type="unknown", choice=str(raw))

    qtype = str(raw.get("type", "unknown"))
    probs_raw = raw.get("probabilities") or {}
    probabilities = {str(k): float(v) for k, v in dict(probs_raw).items()}

    return Answer(
        question_id=question_id,
        type=qtype,
        choice=None if raw.get("choice") is None else str(raw["choice"]),
        noul=None if raw.get("noul") is None else float(raw["noul"]),
        score=raw.get("score"),
        probabilities=probabilities,
        confidence=None if raw.get("confidence") is None else float(raw["confidence"]),
    )


def _extract(payload: dict[str, Any]) -> dict[str, Answer]:
    """Pull answers out of a raw response, tolerating layout differences.

    TypeSafe HTTP nests under `answers`. Some gateways instead group by
    primitive under choices/nouls/scores with the question id as key.
    """
    answers: dict[str, Answer] = {}
    nested = payload.get("answers")
    if isinstance(nested, dict):
        for qid, raw in nested.items():
            answers[str(qid)] = _answer_from_raw(str(qid), raw)
    else:
        for bucket in ("choices", "nouls", "scores"):
            group = payload.get(bucket)
            if isinstance(group, dict):
                for qid, raw in group.items():
                    if str(qid) not in answers:
                        answers[str(qid)] = _answer_from_raw(str(qid), raw)
    if not answers:
        raise SystemOneError(
            "Backend response contained no answers.",
            body=json.dumps(payload)[:500],
        )
    return answers


def _extract_usage(payload: dict[str, Any]) -> Usage:
    usage = payload.get("usage") or {}
    cost = usage.get("cost")
    return Usage(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cost=None if cost is None else float(cost),
    )


def _to_payload(model, state, questions, *, temperature=None):
    """Serialize SDK-style question objects into the HTTP wire format."""

    def field(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    out_questions = {}
    for qid, q in questions.items():
        entry = {"type": str(field(q, "type", "choice"))}
        instructions = field(q, "instructions")
        if instructions is not None:
            entry["instructions"] = instructions
        criteria = field(q, "criteria")
        if criteria is not None:
            entry["criteria"] = criteria
        out_questions[str(qid)] = entry

    payload = {"model": model, "state": state, "questions": out_questions}
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


class JevBackend:
    """Configurable transport for one System One endpoint."""

    def __init__(
        self, backend="auto", *, model=None, base_url=None, api_key=None, timeout=DEFAULT_TIMEOUT
    ) -> None:
        if base_url and backend == "auto":
            resolved = "custom"
        elif backend in ENDPOINTS:
            resolved = backend
        elif backend == "auto":
            resolved = self._autodetect()
        else:
            raise ValueError(
                f"Unknown backend {backend!r}. Use auto/direct/openrouter/ollama or pass base_url."
            )

        self.backend = resolved
        endpoint = ENDPOINTS.get(resolved, "")
        if resolved == "ollama":
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
            if "://" not in host:
                host = f"http://{host}"
            endpoint = f"{host}/v1/systemone"
        self.url = (base_url or endpoint).rstrip("/")
        if not self.url:
            raise ValueError(f"No endpoint known for backend {resolved!r}")
        self.model = model or MODELS.get(resolved, "jev-latest")
        self.api_key = api_key if api_key is not None else os.environ.get(KEY_ENV.get(resolved, ""))
        self.timeout = timeout

    @staticmethod
    def _autodetect() -> str:
        """Pick a backend from whichever credential is present in the env.

        Direct wins when both are set because it is the vendor's own endpoint
        and carries the 64k context (OpenRouter advertises 32k).
        """
        if os.environ.get("TYPESAFE_API_KEY"):
            return "direct"
        if os.environ.get("OPENROUTER_API_KEY"):
            return "openrouter"
        if os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_API_KEY"):
            return "ollama"
        return "ollama"  # local default: no key required

    def describe(self) -> str:
        return f"{self.backend} ({self.model}) -> {self.url}"

    def system_one(self, *, state, questions, model=None) -> SystemOneResponse:
        payload = _to_payload(model or self.model, state, questions)
        body = json.dumps(payload).encode()

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            if exc.code in (401, 403):
                hint = (
                    f"Missing or invalid key for {self.backend}. Set "
                    f"{KEY_ENV.get(self.backend, 'the API key')} and try again."
                )
            elif exc.code == 404:
                hint = (
                    f"{self.backend} rejected the System One endpoint/model. "
                    "This transport needs /v1/systemone, not a chat-completions API."
                )
            elif exc.code == 429:
                hint = "Rate limited. Back off, or lower the decision frequency."
            else:
                hint = "Backend rejected the request."
            raise SystemOneError(f"{hint} (HTTP {exc.code})", status=exc.code, body=detail) from exc
        except urllib.error.URLError as exc:
            if self.backend == "ollama":
                hint = (
                    "Could not reach the local System One server. Check OLLAMA_HOST; "
                    "this route requires /v1/systemone support, not just a chat API."
                )
            else:
                hint = f"Network error reaching {self.url}."
            raise SystemOneError(f"{hint} ({exc.reason})") from exc
        except json.JSONDecodeError as exc:
            raise SystemOneError("Backend returned non-JSON response.") from exc

        latency_ms = (time.perf_counter() - started) * 1000
        return SystemOneResponse(
            _extract(raw),
            _extract_usage(raw),
            model=str(raw.get("model") or payload["model"]),
            backend=self.backend,
            latency_ms=latency_ms,
        )


class MultiBackendClient:
    """Drop-in replacement for typesafe_sdk.TypeSafeClient.

    Exposes system_one(state=..., questions=...) and close(), which is exactly
    what TypeSafePolicy calls.
    """

    def __init__(self, backend="auto", **kwargs) -> None:
        self._backend = JevBackend(backend, **kwargs)

    @property
    def backend(self) -> JevBackend:
        return self._backend

    def describe(self) -> str:
        return self._backend.describe()

    def system_one(self, *, state, questions, model=None) -> SystemOneResponse:
        return self._backend.system_one(state=state, questions=questions, model=model)

    def close(self) -> None:
        return None
