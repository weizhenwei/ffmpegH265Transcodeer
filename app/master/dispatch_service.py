import logging
from datetime import datetime, timedelta

from app.core.enums import TaskStatus
from app.core.models import Task, WorkerNode
from app.infra.db import Database

logger = logging.getLogger(__name__)


class DispatchService:
    def __init__(self, db: Database, queue: object) -> None:
        self.db = db
        self.queue = queue

    @staticmethod
    def _build_weighted_worker_ring(workers: list[WorkerNode]) -> list[str]:
        ring: list[str] = []
        for worker in workers:
            weight = max(1, int(worker.capacity))
            ring.extend([worker.worker_id] * weight)
        return ring

    def dispatch_pending_tasks(self, job_id: str, default_params: dict) -> int:
        count = 0
        logger.info("dispatch started", extra={"event": "dispatch_started", "job_id": job_id})
        with self.db.session() as session:
            heartbeat_deadline = datetime.utcnow() - timedelta(seconds=60)
            workers = (
                session.query(WorkerNode)
                .filter(
                    WorkerNode.status == "online",
                    WorkerNode.last_heartbeat_at >= heartbeat_deadline,
                )
                .order_by(WorkerNode.worker_id.asc())
                .all()
            )
            if not workers:
                logger.warning(
                    "no active workers found, skip dispatch",
                    extra={"event": "dispatch_skipped_no_workers", "job_id": job_id},
                )
                return 0

            worker_ring = self._build_weighted_worker_ring(workers)
            tasks = session.query(Task).filter(Task.job_id == job_id, Task.status == TaskStatus.PENDING.value).all()
            for idx, task in enumerate(tasks):
                target_worker_id = worker_ring[idx % len(worker_ring)]
                payload = {
                    "task_id": task.id,
                    "job_id": task.job_id,
                    "input_path": task.input_path,
                    "output_path": task.output_path,
                    "retry_count": task.retry_count,
                    "max_retry": task.max_retry,
                    "params": default_params,
                    "worker_id": target_worker_id,
                }
                self.queue.push(payload)
                task.status = TaskStatus.DISPATCHED.value
                task.worker_id = target_worker_id
                count += 1
                logger.info(
                    "task dispatched",
                    extra={
                        "event": "task_dispatched",
                        "job_id": job_id,
                        "task_id": task.id,
                        "worker_id": target_worker_id,
                    },
                )
        logger.info("dispatch completed", extra={"event": "dispatch_completed", "job_id": job_id})
        return count
