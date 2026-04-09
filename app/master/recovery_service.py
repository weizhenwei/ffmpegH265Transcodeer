from datetime import datetime, timedelta

from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database


class RecoveryService:
    def __init__(self, db: Database, queue: object) -> None:
        self.db = db
        self.queue = queue

    def reclaim_stuck_tasks(self, timeout_sec: int) -> int:
        deadline = datetime.utcnow() - timedelta(seconds=timeout_sec)
        reclaimed = 0
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
                else:
                    task.status = TaskStatus.FAILED.value
                    task.stderr_summary = "task timeout"
                reclaimed += 1
        return reclaimed
