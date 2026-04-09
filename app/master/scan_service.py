from pathlib import Path

from app.core.enums import TaskStatus
from app.core.models import Task
from app.infra.db import Database
from app.infra.storage import build_output_path, is_supported_file, iter_input_files


class ScanService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def scan_and_create_tasks(
        self,
        job_id: str,
        input_root: str,
        output_root: str,
        output_suffix: str,
        output_mode: str,
        max_retry: int,
    ) -> list[Task]:
        created: list[Task] = []
        files = iter_input_files(input_root)
        with self.db.session() as session:
            for src in files:
                src_path = Path(src)
                if not is_supported_file(src_path):
                    task = Task(
                        job_id=job_id,
                        input_path=str(src_path),
                        output_path="",
                        input_format=src_path.suffix.lower().lstrip("."),
                        status=TaskStatus.SKIPPED.value,
                        max_retry=max_retry,
                        stderr_summary="unsupported format",
                    )
                    session.add(task)
                    created.append(task)
                    continue
                out_path = build_output_path(input_root, output_root, src_path, output_suffix, output_mode)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                task = Task(
                    job_id=job_id,
                    input_path=str(src_path),
                    output_path=str(out_path),
                    input_format=src_path.suffix.lower().lstrip("."),
                    status=TaskStatus.PENDING.value,
                    max_retry=max_retry,
                )
                session.add(task)
                created.append(task)
            session.flush()
            for task in created:
                session.refresh(task)
        return created
