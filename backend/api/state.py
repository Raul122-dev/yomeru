"""Shared in-process state accessible by all API routes."""
import asyncio

# run_id → asyncio.Queue for WebSocket event delivery
# Used by both the pipeline runs and typesetting routes
queues: dict[str, asyncio.Queue] = {}