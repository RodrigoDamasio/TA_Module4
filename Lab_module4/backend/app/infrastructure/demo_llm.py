"""LLM_MODE=fake: deterministic answers — no key, no quota. Used for UI work, local E2E,
and as the base of the test fake. The answer names the top excerpts and cites them, so the
citation check and the UI's source highlighting run exactly as with Gemini."""

import json
import re

from app.domain.ports import LLMRequest, LLMResponse, TokenUsage, UserMessage

_EXCERPT = re.compile(r"^\[(\d+)\] (\S+?)(?: · (.+))?$", re.M)


class DemoLLMClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        prompt = "\n".join(m.text for m in request.messages if isinstance(m, UserMessage))
        name = request.response_schema.__name__ if request.response_schema else "text"
        data = getattr(self, f"_{name}", self._text)(prompt)
        usage = TokenUsage(input=len(prompt) // 4, output=60)
        return LLMResponse(json.dumps(data), [], data, usage, "stop")

    def _AnswerLLM(self, prompt: str) -> dict:  # noqa: N802
        excerpts = _EXCERPT.findall(prompt.split("# Code excerpts", 1)[-1])
        if not excerpts:
            return {"answer": "Demo mode: no excerpts were provided.", "found": False,
                    "citations": []}  # fmt: skip
        top = excerpts[:2]
        names = [f"`{symbol or location}` [{n}]" for n, location, symbol in top]
        answer = (
            "Demo mode (LLM_MODE=fake, no Gemini call): the most relevant code is "
            + " and ".join(names)
            + "."
        )
        return {"answer": answer, "found": True, "citations": [int(n) for n, _, _ in top]}

    def _JudgeLLM(self, prompt: str) -> dict:  # noqa: N802
        reason = "Demo mode: fixed score, no Gemini call."
        return {c: {"score": 4, "reason": reason} for c in ("faithfulness", "relevance",
                                                           "correctness")}  # fmt: skip

    def _text(self, prompt: str) -> dict:
        return {"text": "Demo mode."}
