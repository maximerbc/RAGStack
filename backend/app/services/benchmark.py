from __future__ import annotations

import asyncio
from statistics import mean
from typing import Any

from app.db import Database
from app.events import EventBus
from app.schemas import utc_now
from app.services.chat import ChatService


class BenchmarkService:
    def __init__(self, db: Database, bus: EventBus, chat: ChatService, concurrency: int = 2):
        self.db = db
        self.bus = bus
        self.chat = chat
        self.concurrency = concurrency

    async def run(self, run_id: str) -> None:
        run = self.db.one("SELECT * FROM benchmark_runs WHERE id=?", (run_id,))
        if not run:
            return
        self.db.execute("UPDATE benchmark_runs SET status='running' WHERE id=?", (run_id,))
        cases = [
            self.db.loads(row["payload_json"], {})
            for row in self.db.all("SELECT payload_json FROM eval_cases ORDER BY created_at")
        ]
        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[dict[str, Any]] = []

        async def process(case: dict[str, Any]) -> None:
            async with semaphore:
                current = self.db.one(
                    "SELECT cancel_requested FROM benchmark_runs WHERE id=?", (run_id,)
                )
                if current and current["cancel_requested"]:
                    return
                result = await self.chat.evaluate(
                    case["question"],
                    case.get("history", []),
                    case.get("reference_answer", ""),
                    case.get("relevant_evidence", []),
                )
                result["case_id"] = case["id"]
                results.append(result)
                metrics = aggregate_metrics(results)
                self.db.execute(
                    "UPDATE benchmark_runs SET completed_cases=?, metrics_json=?, results_json=? WHERE id=?",
                    (len(results), self.db.dumps(metrics), self.db.dumps(results), run_id),
                )
                await self.bus.publish(
                    f"benchmark:{run_id}",
                    "case.complete",
                    {
                        "case_id": case["id"],
                        "completed": len(results),
                        "total": len(cases),
                        "metrics": metrics,
                    },
                )

        try:
            await asyncio.gather(*(process(case) for case in cases))
            cancelled = self.db.one(
                "SELECT cancel_requested FROM benchmark_runs WHERE id=?", (run_id,)
            )
            status = "cancelled" if cancelled and cancelled["cancel_requested"] else "completed"
            self.db.execute(
                "UPDATE benchmark_runs SET status=?, finished_at=? WHERE id=?",
                (status, utc_now(), run_id),
            )
            await self.bus.publish(
                f"benchmark:{run_id}",
                status if status == "cancelled" else "complete",
                {"metrics": aggregate_metrics(results)},
            )
        except Exception as exc:
            self.db.execute(
                "UPDATE benchmark_runs SET status='failed', finished_at=? WHERE id=?",
                (utc_now(), run_id),
            )
            await self.bus.publish(f"benchmark:{run_id}", "failed", {"message": str(exc)})


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"cases": 0, "wins": {"rag": 0, "baseline": 0, "tie": 0}}
    wins = {"rag": 0, "baseline": 0, "tie": 0}
    correctness = {"rag": [], "baseline": []}
    retrieval = {"recall_at_k": [], "mrr": [], "ndcg": []}
    citation = {"precision": [], "completeness": []}
    groundedness: list[float] = []
    output_tokens = {"rag": 0, "baseline": 0}
    for result in results:
        judge = result["judge"]
        labels = judge["labels"]
        preference = judge.get("preference", "tie")
        winner = labels.get(preference, "tie") if preference in {"A", "B"} else "tie"
        wins[winner if winner in wins else "tie"] += 1
        for side in ("A", "B"):
            label = labels[side]
            correctness[label].append(float(judge.get(f"correctness_{side.lower()}", 0)))
            groundedness_value = judge.get(f"groundedness_{side.lower()}")
            if label == "rag" and groundedness_value is not None:
                groundedness.append(float(groundedness_value))
        for key in retrieval:
            retrieval[key].append(float(result["retrieval"].get(key, 0)))
        for key in citation:
            citation[key].append(float(result.get("citation", {}).get(key, 0)))
        for variant in output_tokens:
            output_tokens[variant] += int(
                result.get("usage", {}).get(variant, {}).get("output_tokens_estimated", 0)
            )
    return {
        "cases": len(results),
        "wins": wins,
        "mean_correctness": {
            key: mean(values) if values else 0 for key, values in correctness.items()
        },
        "retrieval": {key: mean(values) if values else 0 for key, values in retrieval.items()},
        "citation": {key: mean(values) if values else 0 for key, values in citation.items()},
        "mean_groundedness": mean(groundedness) if groundedness else 0,
        "output_tokens_estimated": output_tokens,
        "mean_latency_ms": mean(result["latency_ms"] for result in results),
    }
