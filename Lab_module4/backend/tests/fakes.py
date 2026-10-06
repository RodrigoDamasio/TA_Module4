"""Test doubles: a scriptable fake LLM (built on the demo client). The fake embedder and
reranker live in app.infrastructure.fake_models (also used by LLM_MODE=fake E2E)."""

import json
import threading
from collections.abc import Callable
from typing import Any

from app.domain.ports import LLMRequest, LLMResponse, TokenUsage, UserMessage
from app.infrastructure.demo_llm import DemoLLMClient

USAGE = TokenUsage(input=100, output=50)


class FakeLLM(DemoLLMClient):
    """Demo answers by default; override per test.

    answers:      list of AnswerLLM dicts (or callables prompt → dict), consumed in order
    judge:        JudgeLLM dict, or callable prompt → dict
    invalid_once: schema names whose FIRST answer is not JSON (tests the repair)
    fail:         {schema name | "any": exception} raised when that schema is requested
    """

    def __init__(self, **options: Any) -> None:
        self.answers: list[dict | Callable[[str], dict]] = list(options.get("answers", []))
        self.judge = options.get("judge")
        self.invalid_once = set(options.get("invalid_once", ()))
        self.fail: dict[str, Exception] = dict(options.get("fail", {}))
        self.requests: list[LLMRequest] = []
        self._lock = threading.Lock()

    def generate(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.requests.append(request)
        name = request.response_schema.__name__ if request.response_schema else "text"
        error = self.fail.get(name) or self.fail.get("any")
        if error is not None:
            raise error
        if name in self.invalid_once:
            self.invalid_once.discard(name)
            return LLMResponse("Sure! Here is the answer...", [], None, USAGE, "stop")
        prompt = "\n".join(m.text for m in request.messages if isinstance(m, UserMessage))
        if name == "AnswerLLM" and self.answers:
            item = self.answers.pop(0)
            data = item(prompt) if callable(item) else item
        elif name == "JudgeLLM" and self.judge is not None:
            data = self.judge(prompt) if callable(self.judge) else self.judge
        else:
            return LLMResponse(*_demo(super().generate(request)))
        return LLMResponse(json.dumps(data), [], data, USAGE, "stop")

    def calls(self, schema: str) -> int:
        return sum(
            1
            for r in self.requests
            if (r.response_schema.__name__ if r.response_schema else "text") == schema
        )

    def last_user_text(self) -> str:
        return "\n".join(m.text for m in self.requests[-1].messages if isinstance(m, UserMessage))


def _demo(response: LLMResponse) -> tuple:
    return response.text, [], response.parsed, USAGE, "stop"


def judge(f: int = 5, r: int = 5, c: int = 5) -> dict:
    return {
        "faithfulness": {"score": f, "reason": "f"},
        "relevance": {"score": r, "reason": "r"},
        "correctness": {"score": c, "reason": "c"},
    }
