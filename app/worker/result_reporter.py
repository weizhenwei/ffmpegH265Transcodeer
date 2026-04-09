from datetime import datetime

from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database


class ResultReporter:
    def __init__(self, db: Database) -> None:
        self.db = db

    def mark_running(self, task_id: str, worker_id: str) -> None:
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = TaskStatus.RUNNING.value
            task.worker_id = worker_id
            task.started_at = datetime.utcnow()

    def mark_success(self, task_id: str, ffprobe_json: str, duration_ms: int) -> None:
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = TaskStatus.SUCCESS.value
            task.ffprobe_json = ffprobe_json
            task.duration_ms = duration_ms
            task.ended_at = datetime.utcnow()

    def mark_failure(self, task_id: str, stderr_summary: str, retry_count: int, max_retry: int) -> bool:
        with self.db.session() as session:
            task = session.get(Task, task_id)
            if task is None:
                return False
            task.stderr_summary = stderr_summary[:2000]
            task.retry_count = retry_count
            task.ended_at = datetime.utcnow()
            if retry_count >= max_retry:
                task.status = TaskStatus.FAILED.value
                return False
            task.status = TaskStatus.RETRYING.value
            return True
