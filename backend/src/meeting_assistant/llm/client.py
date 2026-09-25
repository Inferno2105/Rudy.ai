"""Client for the local Ollama server.

One wrapper, injected into every stage that needs a language model, replacing
three modules that each hardcoded the model name and their own call boilerplate.
Injection is what makes those stages testable without a running server — a fake
with the same two methods substitutes cleanly — and it means the model is named
in exactly one place, which matters when the choice of model is itself an
experimental variable.

Per-call latency and token counts are accumulated because they are reportable
results: this pipeline runs a 7B model on CPU, and "how long does a meeting take
to process locally" is a genuine finding rather than an implementation detail.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from meeting_assistant import config
from meeting_assistant.errors import LLMError
from meeting_assistant.llm.json_parse import extract_json
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class LLMUsage:
    """Accumulated cost of a stage's language-model calls."""

    calls: int = 0
    failures: int = 0
    retries: int = 0
    total_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def record(
        self,
        *,
        seconds: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self.calls += 1
        self.total_seconds += seconds
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "retries": self.retries,
            "total_seconds": round(self.total_seconds, 2),
            "mean_seconds": round(self.total_seconds / self.calls, 2) if self.calls else 0.0,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


@dataclass
class OllamaClient:
    """Thin wrapper over ``ollama.Client``.

    Args:
        model: model tag. Defaults to the configured one.
        host: server URL. Defaults to the configured one.
        temperature: low by default. Every use of a model in this pipeline is an
            extraction or conversion task — rewriting script, summarizing what
            was said, listing tasks that were assigned — where invention is the
            failure mode, so sampling creativity is actively unwanted.
        timeout: seconds. Generous because a 7B model on CPU is slow.
    """

    model: str = field(default_factory=lambda: config.OLLAMA_MODEL)
    host: str = field(default_factory=lambda: config.OLLAMA_HOST)
    temperature: float = 0.1
    timeout: float = 180.0
    usage: LLMUsage = field(default_factory=LLMUsage)
    _client: Any = field(default=None, repr=False)

    def _get_client(self) -> Any:
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self.host, timeout=self.timeout)
        return self._client

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Send one chat request and return the reply text.

        Raises:
            LLMError: on any transport or server failure.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        try:
            response = self._get_client().chat(
                model=self.model,
                messages=messages,
                options={"temperature": self.temperature},
            )
        except Exception as exc:
            self.usage.failures += 1
            raise LLMError(
                f"Ollama request failed ({type(exc).__name__}: {exc}). "
                f"Is the server running at {self.host} and has `ollama pull "
                f"{self.model}` been run?"
            ) from exc

        elapsed = time.perf_counter() - started
        self.usage.record(
            seconds=elapsed,
            prompt_tokens=int(response.get("prompt_eval_count") or 0),
            completion_tokens=int(response.get("eval_count") or 0),
        )

        content = (response.get("message") or {}).get("content") or ""
        return content.strip()

    def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        expect: type = dict,
        retries: int = 1,
    ) -> Any:
        """Send a request and parse the reply as JSON, retrying once on garbage.

        The retry appends a blunter instruction rather than re-sending the same
        prompt, since an identical request to a low-temperature model tends to
        produce an identical malformed reply. One retry only: if restating the
        requirement does not work, more attempts cost minutes of CPU time for no
        better odds, and the caller treats it as a soft failure anyway.

        Raises:
            LLMError: if no attempt produced parseable JSON.
        """
        attempt_prompt = prompt
        last_error: LLMError | None = None

        for attempt in range(retries + 1):
            raw = self.generate(attempt_prompt, system=system)
            try:
                return extract_json(raw, expect=expect)
            except LLMError as exc:
                last_error = exc
                if attempt < retries:
                    self.usage.retries += 1
                    log.warning("Model did not return valid JSON; retrying once. %s", exc)
                    attempt_prompt = (
                        f"{prompt}\n\n"
                        "Your previous response could not be parsed. Respond with "
                        "ONLY the raw JSON object, with no markdown code fences, "
                        "no explanation and no text before or after it."
                    )

        self.usage.failures += 1
        raise last_error  # type: ignore[misc]

    def health_check(self) -> tuple[bool, str]:
        """Check the server is reachable and the model is present.

        Returns ``(ok, detail)`` rather than raising, because this runs inside
        diagnostics that want to report every problem at once. Distinguishes "no
        server" from "server but model not pulled" — different fixes.
        """
        try:
            import ollama
        except ImportError:
            return False, "the `ollama` Python package is not installed"

        try:
            client = ollama.Client(host=self.host, timeout=10.0)
            listed = client.list()
        except Exception as exc:
            return False, f"cannot reach the server ({type(exc).__name__}: {exc})"

        names = {
            model.get("name") or model.get("model") or ""
            for model in (listed.get("models") or [])
        }
        # Ollama reports tags as "qwen2.5:7b"; accept a bare name matching too.
        if self.model in names or any(n.split(":")[0] == self.model.split(":")[0] for n in names):
            return True, f"reachable, model {self.model} available"
        available = ", ".join(sorted(n for n in names if n)) or "none"
        return False, f"model {self.model} not pulled (available: {available})"
