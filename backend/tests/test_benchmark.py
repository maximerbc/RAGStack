import pytest
from app.services.benchmark import aggregate_metrics


def test_aggregate_metrics_resolves_blinded_labels():
    results = [
        {
            "judge": {
                "labels": {"A": "baseline", "B": "rag"},
                "preference": "B",
                "correctness_a": 0.4,
                "correctness_b": 0.9,
            },
            "retrieval": {"recall_at_k": 1, "mrr": 0.5, "ndcg": 0.7},
            "latency_ms": 100,
        },
        {
            "judge": {
                "labels": {"A": "rag", "B": "baseline"},
                "preference": "A",
                "correctness_a": 0.8,
                "correctness_b": 0.5,
            },
            "retrieval": {"recall_at_k": 0.5, "mrr": 1, "ndcg": 0.9},
            "latency_ms": 200,
        },
    ]
    metrics = aggregate_metrics(results)
    assert metrics["wins"]["rag"] == 2
    assert metrics["mean_correctness"]["rag"] == pytest.approx(0.85)
    assert metrics["retrieval"]["recall_at_k"] == 0.75
