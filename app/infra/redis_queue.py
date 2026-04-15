import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
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


class DatabaseQueue:
    def __init__(self, db: object) -> None:
        self.db = db

    def push(self, payload: dict[str, Any]) -> str:
        from app.core.enums import TaskStatus
        from app.core.models import Task

        task_id = payload.get("task_id")
        if task_id is None:
            return ""
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                return str(task_id)
            task.status = TaskStatus.DISPATCHED.value
            if "worker_id" in payload:
                task.worker_id = payload.get("worker_id")
            task.retry_count = int(payload.get("retry_count", task.retry_count))
            task.max_retry = int(payload.get("max_retry", task.max_retry))
            logger.debug("database queue push task_id=%s", task_id)
            return task.id

    def pop(self, consumer: str, block_ms: int = 5000, count: int = 1) -> list[QueueMessage]:
        from app.core.enums import TaskStatus
        from app.core.models import Job, Task

        timeout_at = time.time() + (block_ms / 1000 if block_ms > 0 else 0)
        while True:
            messages: list[QueueMessage] = []
            with self.db.session() as session:
                candidate_ids = (
                    session.query(Task.id)
                    .filter(Task.status == TaskStatus.DISPATCHED.value)
                    .filter((Task.worker_id == consumer) | (Task.worker_id.is_(None)))
                    .order_by(Task.created_at.asc())
                    .limit(max(count * 4, count))
                    .all()
                )
                for (task_id,) in candidate_ids:
                    updated = (
                        session.query(Task)
                        .filter(
                            Task.id == task_id,
                            Task.status == TaskStatus.DISPATCHED.value,
                            ((Task.worker_id == consumer) | (Task.worker_id.is_(None))),
                        )
                        .update(
                            {
                                Task.status: TaskStatus.RUNNING.value,
                                Task.worker_id: consumer,
                                Task.started_at: datetime.utcnow(),
                            },
                            synchronize_session=False,
                        )
                    )
                    if updated != 1:
                        continue
                    task = session.get(Task, task_id)
                    if task is None:
                        continue
                    params: dict[str, Any] = {}
                    job = session.get(Job, task.job_id)
                    if job is not None and job.params_json:
                        try:
                            params = json.loads(job.params_json)
                        except json.JSONDecodeError:
                            params = {}
                    payload = {
                        "task_id": task.id,
                        "job_id": task.job_id,
                        "input_path": task.input_path,
                        "output_path": task.output_path,
                        "retry_count": task.retry_count,
                        "max_retry": task.max_retry,
                        "params": params,
                    }
                    messages.append(QueueMessage(message_id=task.id, payload=payload))
                    if len(messages) >= count:
                        break
            if messages:
                logger.debug("database queue pop count=%s consumer=%s", len(messages), consumer)
                return messages
            if block_ms <= 0 or time.time() >= timeout_at:
                return []
            time.sleep(0.2)

    def ack(self, message_id: str) -> None:
        logger.debug("database queue ack message_id=%s", message_id)
        return None
