"""
WebSocket handler — unified progress stream for phase execution.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

# Per-run event queues for WS consumers
_queues: dict[str, asyncio.Queue] = {}


def get_queue(run_id: str) -> asyncio.Queue:
    """Get or create a queue for a run."""
    if run_id not in _queues:
        _queues[run_id] = asyncio.Queue()
    return _queues[run_id]


def remove_queue(run_id: str) -> None:
    """Clean up queue after WS disconnects."""
    _queues.pop(run_id, None)


def make_emitter(run_id: str):
    """Create a progress callback that pushes events into the run's WS queue."""
    def emit(event: dict) -> None:
        try:
            # Always get current queue (not a captured reference) to handle reconnections
            queue = get_queue(run_id)
            queue.put_nowait(event)
        except Exception:
            pass

    return emit


async def ws_handler(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint handler — streams events from the run's queue."""
    await websocket.accept()
    queue = get_queue(run_id)

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await websocket.send_json({"type": "heartbeat"})
    except (WebSocketDisconnect, Exception):
        pass
