import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any, Protocol

from redis.asyncio import Redis

Message = dict[str, Any]


class Broker(Protocol):
    async def publish(self, channel: str, message: Message) -> None: ...

    def subscribe(self, channel: str) -> AsyncIterator[Message]: ...

    async def aclose(self) -> None: ...


class InMemoryBroker:
    """Process-local fanout used when Redis is unavailable."""

    def __init__(self, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[Message]]] = defaultdict(set)

    async def publish(self, channel: str, message: Message) -> None:
        for queue in list(self._subscribers.get(channel, ())):
            while True:
                try:
                    queue.put_nowait(message)
                    break
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass

    async def subscribe(self, channel: str) -> AsyncIterator[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[channel].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(channel)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(channel, None)

    async def aclose(self) -> None:
        self._subscribers.clear()


class RedisBroker:
    """Redis pub/sub fanout so multiple API workers observe the same stream."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis | None = None

    def _connection(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    async def ping(self) -> None:
        await self._connection().ping()

    async def publish(self, channel: str, message: Message) -> None:
        await self._connection().publish(channel, json.dumps(message, default=str))

    async def subscribe(self, channel: str) -> AsyncIterator[Message]:
        pubsub = self._connection().pubsub()
        await pubsub.subscribe(channel)
        try:
            async for item in pubsub.listen():
                if item.get("type") != "message":
                    continue
                try:
                    yield json.loads(item["data"])
                except (TypeError, ValueError):
                    continue
        finally:
            try:
                await pubsub.unsubscribe(channel)
            finally:
                await pubsub.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            await client.aclose()
