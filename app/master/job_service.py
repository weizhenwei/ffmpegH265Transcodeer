import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.enums import JobStatus, TaskStatus, TriggerType
from app.core.models import Job, Task
from app.infra.db import Database


class JobService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_job(
        self,
        input_root: str,
        output_root: str,
        params: dict[str, Any],
        trigger_type: TriggerType = TriggerType.MANUAL,
    ) -> Job:
        if not Path(input_root).exists():
            raise FileNotFoundError(f"input path not found: {input_root}")
        Path(output_root).mkdir(parents=True, exist_ok=True)
        with self.db.session() as session:
            job = Job(
                trigger_type=trigger_type.value,
                input_root=input_root,
                output_root=output_root,
                params_json=json.dumps(params, ensure_ascii=False),
                status=JobStatus.PENDING.value,
            )
            session.add(job)
            session.flush()
            session.refresh(job)
            return job

    def mark_running(self, job_id: str) -> None:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.status = JobStatus.RUNNING.value
            job.started_at = datetime.utcnow()

    def refresh_job_status(self, job_id: str) -> None:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            totals = session.execute(
                select(Task.status, func.count(Task.id)).where(Task.job_id == job_id).group_by(Task.status)
            ).all()
            stats = {status: count for status, count in totals}
            job.total_count = sum(stats.values())
            job.success_count = stats.get(TaskStatus.SUCCESS.value, 0)
            job.failed_count = stats.get(TaskStatus.FAILED.value, 0)
            job.skipped_count = stats.get(TaskStatus.SKIPPED.value, 0)
            if job.total_count == 0:
                job.status = JobStatus.SUCCESS.value
                job.ended_at = datetime.utcnow()
                return
            if job.success_count == job.total_count:
                job.status = JobStatus.SUCCESS.value
                job.ended_at = datetime.utcnow()
            elif job.failed_count == job.total_count:
                job.status = JobStatus.FAILED.value
                job.ended_at = datetime.utcnow()
            elif job.success_count > 0 and job.failed_count > 0:
                job.status = JobStatus.PARTIAL_SUCCESS.value
                job.ended_at = datetime.utcnow()

    def get_job(self, job_id: str) -> Job | None:
        with self.db.session() as session:
            return session.get(Job, job_id)
