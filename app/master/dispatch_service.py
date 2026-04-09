from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database


class DispatchService:
    def __init__(self, db: Database, queue: object) -> None:
        self.db = db
        self.queue = queue

    def dispatch_pending_tasks(self, job_id: str, default_params: dict) -> int:
        count = 0
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
        return count
