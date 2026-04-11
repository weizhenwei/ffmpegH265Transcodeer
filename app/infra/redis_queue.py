import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

try:
    import redis
except Exception:
    redis = None

logger = logging.getLogger(__name__)


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
        logger.info("redis queue initialized", extra={"event": "redis_queue_initialized"})

    def _bootstrap_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream_key, self.group, id="0", mkstream=True)
        except redis.exceptions.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def push(self, payload: dict[str, Any]) -> str:
        message_id = self.client.xadd(self.stream_key, {"data": json.dumps(payload, ensure_ascii=False)})
        logger.debug("queue push message_id=%s", message_id)
        return message_id

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
        if messages:
            logger.debug("queue pop count=%s consumer=%s", len(messages), consumer)
        return messages

    def ack(self, message_id: str) -> None:
        self.client.xack(self.stream_key, self.group, message_id)
        logger.debug("queue ack message_id=%s", message_id)


class InMemoryQueue:
    def __init__(self) -> None:
        self.store: deque[tuple[str, dict[str, Any]]] = deque()
        self.seq = 0

    def push(self, payload: dict[str, Any]) -> str:
        self.seq += 1
        message_id = str(self.seq)
        self.store.append((message_id, payload))
        logger.debug("in-memory queue push message_id=%s", message_id)
        return message_id

    def pop(self, consumer: str, block_ms: int = 0, count: int = 1) -> list[QueueMessage]:
        result: list[QueueMessage] = []
        for _ in range(min(count, len(self.store))):
            message_id, payload = self.store.popleft()
            result.append(QueueMessage(message_id=message_id, payload=payload))
        if result:
            logger.debug("in-memory queue pop count=%s consumer=%s", len(result), consumer)
        return result

    def ack(self, message_id: str) -> None:
        return None
