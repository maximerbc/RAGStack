from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import tiktoken
from app.db import Database
from app.schemas import utc_now
from app.services.openai_service import AIProvider
from app.services.retrieval import RetrievalService, validate_citation_ids

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class ChatService:
    def __init__(self, db: Database, ai: AIProvider, retrieval: RetrievalService):
        self.db = db
        self.ai = ai
        self.retrieval = retrieval
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def token_count(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def history(
        self, conversation_id: str, exclude_turn: str | None = None
    ) -> list[dict[str, str]]:
        rows = self.db.all(
            "SELECT id, question, rag_answer FROM turns WHERE conversation_id=? ORDER BY created_at",
            (conversation_id,),
        )
        history: list[dict[str, str]] = []
        for row in rows:
            if row["id"] == exclude_turn:
                continue
            history.append({"role": "user", "content": row["question"]})
            if row["rag_answer"]:
                history.append({"role": "assistant", "content": row["rag_answer"]})
        return history[-8:]

    async def run_turn(
        self,
        turn_id: str,
        compare: bool,
        emit: EventCallback,
        document_ids: list[str] | None = None,
    ) -> None:
        row = self.db.one("SELECT * FROM turns WHERE id=?", (turn_id,))
        if not row:
            return
        question, conversation_id = row["question"], row["conversation_id"]
        history = self.history(conversation_id, exclude_turn=turn_id)
        self.db.execute("UPDATE turns SET status='running' WHERE id=?", (turn_id,))
        try:
            await emit("started", {"turn_id": turn_id})
            trace = await self.retrieval.retrieve(question, history, document_ids)
            await emit("retrieval.complete", trace.model_dump())
            evidence = self.retrieval.evidence_prompt(trace, self.retrieval.index)

            async def collect(kind: str, evidence_text: str | None) -> tuple[str, dict[str, int]]:
                pieces: list[str] = []
                started = time.perf_counter()
                async for delta in self.ai.generate(question, history, evidence_text):
                    pieces.append(delta)
                    await emit("answer.delta", {"variant": kind, "delta": delta})
                answer = "".join(pieces).strip()
                input_text = question + "\n" + "\n".join(item["content"] for item in history)
                if evidence_text:
                    input_text += "\n" + evidence_text
                usage = {
                    "input_tokens_estimated": self.token_count(input_text),
                    "output_tokens_estimated": self.token_count(answer),
                }
                await emit(
                    "answer.complete",
                    {
                        "variant": kind,
                        "answer": answer,
                        "latency_ms": (time.perf_counter() - started) * 1000,
                        "usage": usage,
                    },
                )
                return answer, usage

            if compare:
                rag_result, baseline_result = await asyncio.gather(
                    collect("rag", evidence), collect("baseline", None)
                )
                rag_answer, _rag_usage = rag_result
                baseline_answer, _baseline_usage = baseline_result
            else:
                rag_answer, _rag_usage = await collect("rag", evidence)
                baseline_answer = None
            invalid = validate_citation_ids(rag_answer, trace.evidence)
            if invalid:
                rag_answer += "\n\n_Citation validation removed unknown evidence references._"
                pattern = r"\[(?:" + "|".join(re.escape(item) for item in invalid) + r")\]"
                rag_answer = re.sub(pattern, "", rag_answer)

            judge = None
            if baseline_answer is not None:
                if random.Random(turn_id).random() < 0.5:
                    raw = await self.ai.judge(
                        question, baseline_answer, rag_answer, evidence=evidence
                    )
                    judge = {**raw, "labels": {"A": "baseline", "B": "rag"}, "reference_free": True}
                else:
                    raw = await self.ai.judge(
                        question, rag_answer, baseline_answer, evidence=evidence
                    )
                    judge = {**raw, "labels": {"A": "rag", "B": "baseline"}, "reference_free": True}
                await emit("judge.complete", judge)
            self.db.execute(
                "UPDATE turns SET rag_answer=?, baseline_answer=?, judge_json=?, trace_json=?, status='completed' WHERE id=?",
                (
                    rag_answer,
                    baseline_answer,
                    self.db.dumps(judge),
                    self.db.dumps(trace.model_dump()),
                    turn_id,
                ),
            )
            self.db.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id)
            )
            await emit("complete", {"turn_id": turn_id})
        except Exception as exc:
            self.db.execute("UPDATE turns SET status='failed' WHERE id=?", (turn_id,))
            await emit("failed", {"turn_id": turn_id, "message": str(exc), "retryable": True})

    async def evaluate(
        self, question: str, history: list[dict[str, str]], reference: str, relevant: list[dict]
    ) -> dict[str, Any]:
        started = time.perf_counter()
        trace = await self.retrieval.retrieve(question, history)
        evidence = self.retrieval.evidence_prompt(trace, self.retrieval.index)

        async def collect(evidence_text: str | None) -> tuple[str, dict[str, int]]:
            answer = "".join(
                [part async for part in self.ai.generate(question, history, evidence_text)]
            ).strip()
            input_text = question + "\n" + "\n".join(item["content"] for item in history)
            if evidence_text:
                input_text += "\n" + evidence_text
            return answer, {
                "input_tokens_estimated": self.token_count(input_text),
                "output_tokens_estimated": self.token_count(answer),
            }

        rag_result, baseline_result = await asyncio.gather(collect(evidence), collect(None))
        rag, rag_usage = rag_result
        baseline, baseline_usage = baseline_result
        rng = random.Random(question + reference)
        if rng.random() < 0.5:
            judge = await self.ai.judge(question, baseline, rag, reference, evidence)
            labels = {"A": "baseline", "B": "rag"}
        else:
            judge = await self.ai.judge(question, rag, baseline, reference, evidence)
            labels = {"A": "rag", "B": "baseline"}
        from app.services.retrieval import retrieval_metrics

        cited = re.findall(r"\[(E\d+)\]", rag)
        valid = {item.evidence_id for item in trace.evidence}
        valid_cited = [item for item in cited if item in valid]
        citation_metrics = {
            "precision": len(valid_cited) / len(cited) if cited else 0.0,
            "completeness": len(set(valid_cited)) / len(valid) if valid else 0.0,
        }
        return {
            "question": question,
            "rag_answer": rag,
            "baseline_answer": baseline,
            "judge": {**judge, "labels": labels, "reference_free": not bool(reference)},
            "retrieval": retrieval_metrics(trace, relevant),
            "citation": citation_metrics,
            "usage": {"rag": rag_usage, "baseline": baseline_usage},
            "trace": trace.model_dump(),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
