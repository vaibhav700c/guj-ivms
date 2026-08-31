"""In-process pub/sub event bus with optional Redis fan-out.

Used to push alerts/analytics to control-room WebSocket clients. When
REDIS_URL is configured, events are also published to Redis for horizontal
scaling across multiple backend replicas (Render autoscaling ready).
"""
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._redis = None
        self._redis_task: asyncio.Task | None = None

    async def connect_redis(self, redis_url: str) -> None:
        if not redis_url:
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("Redis connected — cross-replica pub/sub enabled")
            self._redis_task = asyncio.create_task(self._redis_listener())
        except Exception as exc:  # pragma: no cover — Redis optional
            logger.warning("Redis unavailable (%s) — using in-process bus", exc)
            self._redis = None

    async def _redis_listener(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("alerts:new", "analytics:new")
        async for message in pubsub.listen():
            if message is None or message.get("type") != "message":
                continue
            channel = message.get("channel", "")
            data = message.get("data")
            # Redis messages are already serialized payloads
            for queue in list(self._subscribers.get(channel, set())):
                await queue.put(data)

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, default=str)
        if self._redis is not None:
            try:
                await self._redis.publish(channel, data)
                return
            except Exception:
                logger.warning("Redis publish failed — falling back in-process")
        for queue in list(self._subscribers.get(channel, set())):
            await queue.put(data)

    async def subscribe(self, *channels: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        for ch in channels:
            self._subscribers[ch].add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue, *channels: str) -> None:
        for ch in channels:
            self._subscribers[ch].discard(queue)


event_bus = EventBus()
