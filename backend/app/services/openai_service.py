from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.config import Settings
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class AIConfigurationError(RuntimeError):
    pass


class JudgeResult(BaseModel):
    correctness_a: float = Field(ge=0, le=1)
    correctness_b: float = Field(ge=0, le=1)
    completeness_a: float = Field(ge=0, le=1)
    completeness_b: float = Field(ge=0, le=1)
    relevance_a: float = Field(ge=0, le=1)
    relevance_b: float = Field(ge=0, le=1)
    preference: str
    groundedness_a: float | None = Field(default=None, ge=0, le=1)
    groundedness_b: float | None = Field(default=None, ge=0, le=1)
    rationale: str = ""


class AIProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def rewrite(self, question: str, history: list[dict[str, str]]) -> str: ...
    async def generate(
        self, question: str, history: list[dict[str, str]], evidence: str | None
    ) -> AsyncIterator[str]: ...
    async def judge(
        self,
        question: str,
        answer_a: str,
        answer_b: str,
        reference: str = "",
        evidence: str = "",
    ) -> dict[str, Any]: ...


class OpenAIProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if not self.settings.openai_api_key:
            raise AIConfigurationError(
                "OPENAI_API_KEY is not configured; copy .env.example to .env when ready"
            )
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.openai_api_key, max_retries=3, timeout=60
            )
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        output: list[list[float]] = []
        for start in range(0, len(texts), 128):
            response = await self.client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=texts[start : start + 128],
                encoding_format="float",
            )
            output.extend(item.embedding for item in response.data)
        return output

    async def rewrite(self, question: str, history: list[dict[str, str]]) -> str:
        if not history:
            return question
        transcript = "\n".join(f"{item['role']}: {item['content']}" for item in history[-8:])
        prompt = (
            "Rewrite the final user question as one self-contained English search query. "
            "Resolve pronouns and relative dates from the conversation. Return only the query. "
            "Never answer the question and never create multiple queries.\n\n"
            f"Conversation:\n{transcript}\nuser: {question}"
        )
        try:
            response = await self.client.responses.create(
                model=self.settings.openai_rewrite_model,
                input=prompt,
                reasoning={"effort": "low"},
                text={"verbosity": "low"},
            )
            rewritten = response.output_text.strip().replace("\n", " ")
            if not rewritten or len(rewritten) > 1000:
                return question
            return rewritten
        except Exception:
            return question

    async def generate(
        self, question: str, history: list[dict[str, str]], evidence: str | None
    ) -> AsyncIterator[str]:
        system = (
            "Answer the user's question clearly and concisely. "
            if evidence is None
            else "Answer only from the supplied evidence. Cite every factual claim with evidence IDs like [E1]. If evidence is insufficient, say so. "
        )
        input_items: list[dict[str, str]] = [{"role": "developer", "content": system}]
        input_items.extend(history[-8:])
        content = (
            question if evidence is None else f"Question:\n{question}\n\nEvidence:\n{evidence}"
        )
        input_items.append({"role": "user", "content": content})
        stream = await self.client.responses.create(
            model=self.settings.openai_generation_model,
            input=input_items,
            reasoning={"effort": "low"},
            text={"verbosity": "medium"},
            stream=True,
        )
        async for event in stream:
            if getattr(event, "type", "") == "response.output_text.delta":
                yield event.delta

    async def judge(
        self,
        question: str,
        answer_a: str,
        answer_b: str,
        reference: str = "",
        evidence: str = "",
    ) -> dict[str, Any]:
        prompt = f"""You are a strict, impartial evaluator. Score each answer from 0 to 1.
Question: {question}
Reference answer (may be empty): {reference}
Answer A: {answer_a}
Answer B: {answer_b}
Retrieved evidence (may be empty): {evidence}
Score groundedness_a and groundedness_b against the retrieved evidence when available.
Choose preference A, B, or tie. Do not infer that B is the RAG answer."""
        try:
            response = await self.client.responses.parse(
                model=self.settings.openai_judge_model,
                input=prompt,
                text_format=JudgeResult,
            )
            parsed = response.output_parsed
            return parsed.model_dump() if parsed else {}
        except AttributeError:
            response = await self.client.responses.create(
                model=self.settings.openai_judge_model, input=prompt
            )
            return json.loads(response.output_text)


class FakeAIProvider:
    def __init__(self, dimensions: int = 8):
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for index, char in enumerate(text.encode()):
                vector[index % self.dimensions] += char / 255
            magnitude = sum(value * value for value in vector) ** 0.5 or 1
            vectors.append([value / magnitude for value in vector])
        return vectors

    async def rewrite(self, question: str, history: list[dict[str, str]]) -> str:
        if history and question.lower().startswith(("and ", "what about", "how about")):
            prior = next(
                (item["content"] for item in reversed(history) if item["role"] == "user"), ""
            )
            return f"{prior} {question}".strip()
        return question

    async def generate(self, question: str, history: list[dict[str, str]], evidence: str | None):
        answer = (
            f"Mock answer to: {question}"
            if evidence is None
            else f"Evidence-backed answer [E1] to: {question}"
        )
        for token in answer.split(" "):
            await asyncio.sleep(0)
            yield token + " "

    async def judge(
        self,
        question: str,
        answer_a: str,
        answer_b: str,
        reference: str = "",
        evidence: str = "",
    ) -> dict[str, Any]:
        return {
            "correctness_a": 0.5,
            "correctness_b": 0.8,
            "completeness_a": 0.5,
            "completeness_b": 0.8,
            "relevance_a": 0.7,
            "relevance_b": 0.9,
            "preference": "B",
            "groundedness_a": 0.5,
            "groundedness_b": 0.9,
            "rationale": "Deterministic test result",
        }
