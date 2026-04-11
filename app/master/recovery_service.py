from datetime import datetime, timedelta
import logging

from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database

logger = logging.getLogger(__name__)


class RecoveryService:
    def __init__(self, db: Database, queue: object) -> None:
        self.db = db
        self.queue = queue

    def reclaim_stuck_tasks(self, timeout_sec: int) -> int:
        deadline = datetime.utcnow() - timedelta(seconds=timeout_sec)
        reclaimed = 0
        logger.debug("recovery cycle started")
        with self.db.session() as session:
            tasks = (
                session.query(Task)
                .filter(Task.status == TaskStatus.RUNNING.value, Task.started_at.is_not(None), Task.started_at < deadline)
                .all()
            )
            for task in tasks:
                if task.retry_count < task.max_retry:
                    task.retry_count += 1
                    task.status = TaskStatus.RETRYING.value
                    self.queue.push(
                        {
                            "task_id": task.id,
                            "job_id": task.job_id,
                            "input_path": task.input_path,
                            "output_path": task.output_path,
                            "retry_count": task.retry_count,
                            "max_retry": task.max_retry,
                            "params": {},
                        }
                    )
                    task.status = TaskStatus.DISPATCHED.value
                    logger.info(
                        "stuck task re-dispatched",
                        extra={"event": "task_recovered", "job_id": task.job_id, "task_id": task.id},
                    )
                else:
                    task.status = TaskStatus.FAILED.value
                    task.stderr_summary = "task timeout"
                    logger.warning(
                        "stuck task marked failed",
                        extra={"event": "task_recovery_failed", "job_id": task.job_id, "task_id": task.id},
                    )
                reclaimed += 1
        if reclaimed > 0:
            logger.info("recovery cycle completed", extra={"event": "recovery_completed"})
        return reclaimed
