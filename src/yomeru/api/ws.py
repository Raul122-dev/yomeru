"""Progress events: worker threads → every WebSocket client of a run.

Each connected client gets its own bounded asyncio.Queue. Workers publish from
their own threads through `loop.call_soon_threadsafe`, so delivery is immediate
and thread-safe. A small per-run backlog of recent non-token events is replayed
to clients that connect mid-phase.
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

CLIENT_QUEUE_MAX = 2000
BACKLOG_MAX = 200
HEARTBEAT_S = 25.0

_lock = threading.Lock()
_clients: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
_backlog: dict[str, deque] = {}


def _deliver(q: asyncio.Queue, event: dict) -> None:
    if q.full():
        # Slow client: drop its oldest event rather than grow without bound
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(event)


def publish(run_id: str, event: dict) -> None:
    """Thread-safe: callable from worker threads and from the event loop."""
    with _lock:
        if event.get("type") != "token":
            if event.get("type") == "phase_start":
                # New phase: older events are no longer useful for replay
                _backlog[run_id] = deque(maxlen=BACKLOG_MAX)
            _backlog.setdefault(run_id, deque(maxlen=BACKLOG_MAX)).append(event)
        targets = list(_clients.get(run_id, ()))
    for loop, q in targets:
        try:
            loop.call_soon_threadsafe(_deliver, q, event)
        except RuntimeError:  # loop closed
            pass


def make_emitter(run_id: str):
    """Progress callback for phases."""
    def emit(event: dict) -> None:
        publish(run_id, event)
    return emit


async def ws_handler(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_MAX)
    entry = (loop, q)
    with _lock:
        _clients.setdefault(run_id, set()).add(entry)
        replay = list(_backlog.get(run_id, ()))
    try:
        for ev in replay:
            await websocket.send_json({**ev, "replay": True})
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                event = {"type": "heartbeat"}
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        with _lock:
            clients = _clients.get(run_id)
            if clients is not None:
                clients.discard(entry)
                if not clients:
                    _clients.pop(run_id, None)


def client_count(run_id: str) -> int:
    with _lock:
        return len(_clients.get(run_id, ()))
