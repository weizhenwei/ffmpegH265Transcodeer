from datetime import datetime
import logging

from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database

logger = logging.getLogger(__name__)


class ResultReporter:
    def __init__(self, db: Database) -> None:
        self.db = db

    def mark_running(self, task_id: str, worker_id: str) -> None:
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                logger.warning("task not found when mark running", extra={"event": "task_running_not_found", "task_id": task_id})
                return
            task.status = TaskStatus.RUNNING.value
            task.worker_id = worker_id
            task.started_at = datetime.utcnow()
            logger.info("task marked running", extra={"event": "task_running", "task_id": task_id, "node_id": worker_id})

    def mark_success(self, task_id: str, ffprobe_json: str, duration_ms: int) -> None:
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                logger.warning("task not found when mark success", extra={"event": "task_success_not_found", "task_id": task_id})
                return
            task.status = TaskStatus.SUCCESS.value
            task.ffprobe_json = ffprobe_json
            task.duration_ms = duration_ms
            task.ended_at = datetime.utcnow()
            logger.info("task marked success", extra={"event": "task_success", "task_id": task_id, "job_id": task.job_id})

    def mark_failure(self, task_id: str, stderr_summary: str, retry_count: int, max_retry: int) -> bool:
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                logger.warning("task not found when mark failure", extra={"event": "task_failure_not_found", "task_id": task_id})
                return False
            task.stderr_summary = stderr_summary[:2000]
            task.retry_count = retry_count
            task.ended_at = datetime.utcnow()
            if retry_count >= max_retry:
                task.status = TaskStatus.FAILED.value
                logger.error("task marked failed", extra={"event": "task_failed", "task_id": task_id, "job_id": task.job_id})
                return False
            task.status = TaskStatus.RETRYING.value
            logger.warning("task marked retrying", extra={"event": "task_retrying", "task_id": task_id, "job_id": task.job_id})
            return True
