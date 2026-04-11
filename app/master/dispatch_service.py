import logging

from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database

logger = logging.getLogger(__name__)


class DispatchService:
    def __init__(self, db: Database, queue: object) -> None:
        self.db = db
        self.queue = queue

    def dispatch_pending_tasks(self, job_id: str, default_params: dict) -> int:
        count = 0
        logger.info("dispatch started", extra={"event": "dispatch_started", "job_id": job_id})
        with self.db.session() as session:
            tasks = session.query(Task).filter(Task.job_id == job_id, Task.status == TaskStatus.PENDING.value).all()
            for task in tasks:
                payload = {
                    "task_id": task.id,
                    "job_id": task.job_id,
                    "input_path": task.input_path,
                    "output_path": task.output_path,
                    "retry_count": task.retry_count,
                    "max_retry": task.max_retry,
                    "params": default_params,
                }
                self.queue.push(payload)
                task.status = TaskStatus.DISPATCHED.value
                count += 1
                logger.info("task dispatched", extra={"event": "task_dispatched", "job_id": job_id, "task_id": task.id})
        logger.info("dispatch completed", extra={"event": "dispatch_completed", "job_id": job_id})
        return count
