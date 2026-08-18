from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, channel: str, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, "data": data}
        for queue in list(self._subscribers[channel]):
            await queue.put(event)

    async def stream(
        self,
        channel: str,
        terminal_check: Callable[[], dict[str, Any] | None] | None = None,
    ):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers[channel].add(queue)
        try:
            terminal = terminal_check() if terminal_check else None
            if terminal:
                yield f"event: {terminal['type']}\ndata: {json.dumps(terminal.get('data', {}))}\n\n"
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                    if event["type"] in {"complete", "failed", "cancelled"}:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self._subscribers[channel].discard(queue)
