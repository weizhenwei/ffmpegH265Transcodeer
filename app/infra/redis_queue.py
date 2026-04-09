import json
from collections import deque
from dataclasses import dataclass
from typing import Any

try:
    import redis
except Exception:
    redis = None


@dataclass
class QueueMessage:
    message_id: str
    payload: dict[str, Any]


class RedisStreamQueue:
    def __init__(self, url: str, stream_key: str, group: str) -> None:
        if redis is None:
            raise RuntimeError("redis package is not installed")
        self.stream_key = stream_key
        self.group = group
        self.client = redis.Redis.from_url(url, decode_responses=True)
        self._bootstrap_group()

    def _bootstrap_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream_key, self.group, id="0", mkstream=True)
        except redis.exceptions.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def push(self, payload: dict[str, Any]) -> str:
        return self.client.xadd(self.stream_key, {"data": json.dumps(payload, ensure_ascii=False)})

    def pop(self, consumer: str, block_ms: int = 5000, count: int = 1) -> list[QueueMessage]:
        rows = self.client.xreadgroup(
            self.group,
            consumer,
            streams={self.stream_key: ">"},
            count=count,
            block=block_ms,
        )
        messages: list[QueueMessage] = []
        for _, entries in rows:
            for message_id, fields in entries:
                payload = json.loads(fields.get("data", "{}"))
                messages.append(QueueMessage(message_id=message_id, payload=payload))
        return messages

    def ack(self, message_id: str) -> None:
        self.client.xack(self.stream_key, self.group, message_id)


class InMemoryQueue:
    def __init__(self) -> None:
        self.store: deque[tuple[str, dict[str, Any]]] = deque()
        self.seq = 0

    def push(self, payload: dict[str, Any]) -> str:
        self.seq += 1
        message_id = str(self.seq)
        self.store.append((message_id, payload))
        return message_id

    def pop(self, consumer: str, block_ms: int = 0, count: int = 1) -> list[QueueMessage]:
        result: list[QueueMessage] = []
        for _ in range(min(count, len(self.store))):
            message_id, payload = self.store.popleft()
            result.append(QueueMessage(message_id=message_id, payload=payload))
        return result

    def ack(self, message_id: str) -> None:
        return None
