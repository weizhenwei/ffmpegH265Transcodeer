import json
import logging
import time
from pathlib import Path

import typer
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.core.logger import setup_logging
from app.core.models import Task
from app.infra.db import Database
from app.infra.metrics import job_total, start_metrics_server
from app.infra.redis_queue import InMemoryQueue, RedisStreamQueue
from app.master.aggregation_service import AggregationService
from app.master.dispatch_service import DispatchService
from app.master.job_service import JobService
from app.master.recovery_service import RecoveryService
from app.master.scan_service import ScanService
from app.master.scheduler_service import SchedulerService
from app.worker.consumer import WorkerConsumer
from app.worker.heartbeat import HeartbeatService
from app.worker.probe_executor import ProbeExecutor
from app.worker.result_reporter import ResultReporter
from app.worker.transcode_executor import TranscodeExecutor

cli = typer.Typer(help="H.265 distributed transcoder CLI")
logger = logging.getLogger(__name__)


def get_queue(settings):
    try:
        return RedisStreamQueue(settings.redis.url, settings.redis.stream_key, settings.redis.group)
    except Exception:
        logger.warning("redis unavailable, fallback to in-memory queue")
        return InMemoryQueue()


def get_db(settings) -> Database:
    db = Database(settings.db.url)
    db.create_all()
    return db


@cli.command()
def submit(
    input_root: str = typer.Option(...),
    output_root: str = typer.Option(...),
    suffix: str = typer.Option("_h265"),
    mode: str = typer.Option("mirror"),
    crf: int = typer.Option(28),
    max_retry: int = typer.Option(2),
) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    db = get_db(settings)
    queue = get_queue(settings)
    job_service = JobService(db)
    scan_service = ScanService(db)
    dispatch_service = DispatchService(db, queue)
    params = {
        "video_codec": settings.transcode.video_codec,
        "crf": crf,
        "preset": settings.transcode.preset,
        "gop": settings.transcode.gop,
        "audio_codec": settings.transcode.audio_codec,
        "audio_bitrate": settings.transcode.audio_bitrate,
    }
    job = job_service.create_job(input_root, output_root, params)
    job_service.mark_running(job.id)
    tasks = scan_service.scan_and_create_tasks(
        job_id=job.id,
        input_root=input_root,
        output_root=output_root,
        output_suffix=suffix,
        output_mode=mode,
        max_retry=max_retry,
    )
    dispatched = dispatch_service.dispatch_pending_tasks(job.id, params)
    job_total.labels(status="RUNNING").inc()
    typer.echo(json.dumps({"job_id": job.id, "task_total": len(tasks), "dispatched": dispatched}, ensure_ascii=False))


@cli.command()
def status(job_id: str = typer.Option(...)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    db = get_db(settings)
    job_service = JobService(db)
    aggregation = AggregationService(job_service)
    aggregation.aggregate(job_id)
    job = job_service.get_job(job_id)
    if job is None:
        raise typer.BadParameter("job not found")
    payload = {
        "job_id": job.id,
        "status": job.status,
        "total": job.total_count,
        "success": job.success_count,
        "failed": job.failed_count,
        "skipped": job.skipped_count,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False))


@cli.command("retry-failed")
def retry_failed(job_id: str = typer.Option(...)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    db = get_db(settings)
    queue = get_queue(settings)
    resent = 0
    with db.session() as session:
        rows = session.execute(select(Task).where(Task.job_id == job_id, Task.status == TaskStatus.FAILED.value)).scalars().all()
        for task in rows:
            if task.retry_count >= task.max_retry:
                continue
            task.status = TaskStatus.DISPATCHED.value
            task.retry_count += 1
            queue.push(
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
            resent += 1
    typer.echo(json.dumps({"job_id": job_id, "resent": resent}, ensure_ascii=False))


@cli.command("run-master")
def run_master(recovery_interval_sec: int = typer.Option(20), metrics_port: int = typer.Option(9108)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    start_metrics_server(metrics_port)
    db = get_db(settings)
    queue = get_queue(settings)
    recovery = RecoveryService(db, queue)
    logger.info("master started")
    while True:
        recovery.reclaim_stuck_tasks(settings.transcode.task_timeout_sec)
        time.sleep(recovery_interval_sec)


@cli.command("run-worker")
def run_worker(metrics_port: int = typer.Option(9109)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    start_metrics_server(metrics_port)
    db = get_db(settings)
    queue = get_queue(settings)
    heartbeat = HeartbeatService(db)
    reporter = ResultReporter(db)
    probe_executor = ProbeExecutor(settings.transcode.ffprobe_bin)
    transcode_executor = TranscodeExecutor(settings.transcode.ffmpeg_bin)
    consumer = WorkerConsumer(
        queue=queue,
        reporter=reporter,
        probe_executor=probe_executor,
        transcode_executor=transcode_executor,
        worker_id=settings.worker.worker_id,
        task_timeout_sec=settings.transcode.task_timeout_sec,
        poll_block_ms=settings.worker.poll_block_ms,
        heartbeat_interval_sec=settings.worker.heartbeat_interval_sec,
        heartbeat_fn=lambda: heartbeat.beat(settings.worker.worker_id, settings.worker.concurrency),
    )
    logger.info("worker started")
    consumer.run_forever()


@cli.command("run-scheduler")
def run_scheduler() -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    scheduler = SchedulerService()

    def tick() -> None:
        logger.info("scheduler tick")

    scheduler.add_cron_job(settings.scheduler.cron, tick)
    scheduler.run()


@cli.command("init")
def init_project() -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    settings.ensure_directories()
    db = get_db(settings)
    db.create_all()
    Path("logs").mkdir(exist_ok=True)
    typer.echo("initialized")


if __name__ == "__main__":
    cli()
