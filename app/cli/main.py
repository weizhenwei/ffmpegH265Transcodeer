import json
import logging
import os
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path

import typer
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.core.logger import setup_logging
from app.core.models import Job, Task, WorkerNode
from app.infra.db import Database
from app.infra.metrics import job_total, start_metrics_server
from app.infra.redis_queue import DatabaseQueue
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


def get_queue(settings, db: Database):
    logger.info(
        "redis disabled, using database queue",
        extra={"event": "queue_backend_database", "service": settings.app.service_name, "node_id": settings.app.node_id},
    )
    return DatabaseQueue(db)


def get_db(settings) -> Database:
    db = Database(settings.db.url)
    db.create_all()
    mode = "distributed" if "postgres" in settings.db.url else "standalone"
    logger.info(
        f"database ready (mode: {mode})",
        extra={"event": "database_ready", "mode": mode, "service": settings.app.service_name, "node_id": settings.app.node_id},
    )
    return db


def submit_job(
    db: Database,
    queue: object,
    *,
    input_root: str,
    output_root: str,
    suffix: str,
    mode: str,
    crf: int,
    max_retry: int,
    settings: object,
) -> dict:
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
    return {"job_id": job.id, "task_total": len(tasks), "dispatched": dispatched}


def update_worker_online_status(db: Database, stale_after_sec: int = 30) -> int:
    offline_count = 0
    deadline = datetime.utcnow() - timedelta(seconds=stale_after_sec)
    with db.session() as session:
        stale_workers = (
            session.query(WorkerNode)
            .filter(WorkerNode.status == "online", WorkerNode.last_heartbeat_at < deadline)
            .all()
        )
        for worker in stale_workers:
            worker.status = "offline"
            offline_count += 1
    return offline_count


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
    logger.info(
        "submit command started",
        extra={"event": "cli_submit_start", "service": settings.app.service_name, "node_id": settings.app.node_id},
    )
    db = get_db(settings)
    queue = get_queue(settings, db)
    result = submit_job(
        db,
        queue,
        input_root=input_root,
        output_root=output_root,
        suffix=suffix,
        mode=mode,
        crf=crf,
        max_retry=max_retry,
        settings=settings,
    )
    job_total.labels(status="RUNNING").inc()
    logger.info(
        "submit command completed",
        extra={
            "event": "cli_submit_done",
            "service": settings.app.service_name,
            "node_id": settings.app.node_id,
            "job_id": result["job_id"],
        },
    )
    typer.echo(json.dumps(result, ensure_ascii=False))


@cli.command("start-transcode")
def start_transcode(
    crf: int = typer.Option(28),
    max_retry: int = typer.Option(2),
) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    db = get_db(settings)
    queue = get_queue(settings, db)
    result = submit_job(
        db,
        queue,
        input_root=settings.storage.input_root,
        output_root=settings.storage.output_root,
        suffix=settings.storage.output_suffix,
        mode=settings.storage.output_mode,
        crf=crf,
        max_retry=max_retry,
        settings=settings,
    )
    typer.echo(json.dumps(result, ensure_ascii=False))


@cli.command()
def status(job_id: str = typer.Option(...)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    logger.info(
        "status command started",
        extra={"event": "cli_status_start", "service": settings.app.service_name, "node_id": settings.app.node_id, "job_id": job_id},
    )
    db = get_db(settings)
    job_service = JobService(db)
    aggregation = AggregationService(job_service)
    aggregation.aggregate(job_id)
    job = job_service.get_job(job_id)
    if job is None:
        logger.error(
            "job not found",
            extra={"event": "job_not_found", "service": settings.app.service_name, "node_id": settings.app.node_id, "job_id": job_id},
        )
        raise typer.BadParameter("job not found")
    payload = {
        "job_id": job.id,
        "status": job.status,
        "total": job.total_count,
        "success": job.success_count,
        "failed": job.failed_count,
        "skipped": job.skipped_count,
    }
    logger.info(
        "status command completed",
        extra={"event": "cli_status_done", "service": settings.app.service_name, "node_id": settings.app.node_id, "job_id": job.id},
    )
    typer.echo(json.dumps(payload, ensure_ascii=False))


@cli.command("retry-failed")
def retry_failed(job_id: str = typer.Option(...)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    logger.info(
        "retry-failed command started",
        extra={"event": "cli_retry_failed_start", "service": settings.app.service_name, "node_id": settings.app.node_id, "job_id": job_id},
    )
    db = get_db(settings)
    queue = get_queue(settings, db)
    resent = 0
    with db.session() as session:
        rows = session.execute(select(Task).where(Task.job_id == job_id, Task.status == TaskStatus.FAILED.value)).scalars().all()
        for task in rows:
            if task.retry_count >= task.max_retry:
                continue
            task.status = TaskStatus.DISPATCHED.value
            task.worker_id = None
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
                    "worker_id": None,
                }
            )
            resent += 1
            logger.info(
                "failed task requeued",
                extra={
                    "event": "task_requeued",
                    "service": settings.app.service_name,
                    "node_id": settings.app.node_id,
                    "job_id": task.job_id,
                    "task_id": task.id,
                },
            )
    logger.info(
        "retry-failed command completed",
        extra={"event": "cli_retry_failed_done", "service": settings.app.service_name, "node_id": settings.app.node_id, "job_id": job_id},
    )
    typer.echo(json.dumps({"job_id": job_id, "resent": resent}, ensure_ascii=False))


@cli.command("run-master")
def run_master(recovery_interval_sec: int = typer.Option(20), metrics_port: int = typer.Option(9108)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    start_metrics_server(metrics_port)
    db = get_db(settings)
    queue = get_queue(settings, db)
    recovery = RecoveryService(db, queue)
    logger.info(
        "master started",
        extra={"event": "master_started", "service": settings.app.service_name, "node_id": settings.app.node_id},
    )
    while True:
        offline_count = update_worker_online_status(db, stale_after_sec=max(30, settings.worker.heartbeat_interval_sec * 3))
        if offline_count > 0:
            logger.warning(
                "workers marked offline due to heartbeat timeout",
                extra={
                    "event": "workers_marked_offline",
                    "service": settings.app.service_name,
                    "node_id": settings.app.node_id,
                    "count": offline_count,
                },
            )
        reclaimed = recovery.reclaim_stuck_tasks(settings.transcode.task_timeout_sec)
        if reclaimed > 0:
            logger.info(
                "master reclaimed tasks",
                extra={"event": "master_reclaimed_tasks", "service": settings.app.service_name, "node_id": settings.app.node_id},
            )
        time.sleep(recovery_interval_sec)


@cli.command("run-worker")
def run_worker(metrics_port: int = typer.Option(9109)) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    start_metrics_server(metrics_port)
    db = get_db(settings)
    queue = get_queue(settings, db)
    worker_id = settings.worker.worker_id.strip() or f"{socket.gethostname()}-{os.getpid()}"
    heartbeat = HeartbeatService(db)
    reporter = ResultReporter(db)
    probe_executor = ProbeExecutor(settings.transcode.ffprobe_bin)
    transcode_executor = TranscodeExecutor(settings.transcode.ffmpeg_bin)
    consumer = WorkerConsumer(
        queue=queue,
        reporter=reporter,
        probe_executor=probe_executor,
        transcode_executor=transcode_executor,
        worker_id=worker_id,
        task_timeout_sec=settings.transcode.task_timeout_sec,
        poll_block_ms=settings.worker.poll_block_ms,
        heartbeat_interval_sec=settings.worker.heartbeat_interval_sec,
        heartbeat_fn=lambda: heartbeat.beat(worker_id, settings.worker.concurrency),
    )
    logger.info(
        "worker started",
        extra={"event": "worker_started", "service": settings.app.service_name, "node_id": worker_id},
    )
    consumer.run_forever()


@cli.command("run-scheduler")
def run_scheduler() -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    scheduler = SchedulerService()
    logger.info(
        "scheduler started",
        extra={"event": "scheduler_started", "service": settings.app.service_name, "node_id": settings.app.node_id},
    )

    def tick() -> None:
        logger.info(
            "scheduler tick",
            extra={"event": "scheduler_tick", "service": settings.app.service_name, "node_id": settings.app.node_id},
        )

    scheduler.add_cron_job(settings.scheduler.cron, tick)
    scheduler.run()


@cli.command("workers")
def workers() -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    db = get_db(settings)
    with db.session() as session:
        rows = session.query(WorkerNode).order_by(WorkerNode.worker_id.asc()).all()
        payload = [
            {
                "worker_id": row.worker_id,
                "hostname": row.hostname,
                "capacity": row.capacity,
                "status": row.status,
                "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
            }
            for row in rows
        ]
    typer.echo(json.dumps({"workers": payload, "total": len(payload)}, ensure_ascii=False))


@cli.command("stats")
def stats(job_id: str = typer.Option("", help="可选，按 job_id 过滤统计")) -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    db = get_db(settings)
    with db.session() as session:
        task_query = session.query(Task.status, func.count(Task.id))
        if job_id:
            task_query = task_query.filter(Task.job_id == job_id)
        task_rows = task_query.group_by(Task.status).all()
        task_stats = {status: count for status, count in task_rows}

        worker_rows = session.query(WorkerNode.status, func.count(WorkerNode.worker_id)).group_by(WorkerNode.status).all()
        worker_stats = {status: count for status, count in worker_rows}

        job_query = session.query(func.count(Job.id))
        if job_id:
            job_query = job_query.filter(Job.id == job_id)
        total_jobs = job_query.scalar() or 0

    typer.echo(
        json.dumps(
            {
                "job_id": job_id or None,
                "jobs_total": total_jobs,
                "task_stats": task_stats,
                "worker_stats": worker_stats,
            },
            ensure_ascii=False,
        )
    )


@cli.command("init")
def init_project() -> None:
    settings = get_settings()
    setup_logging(settings.app.log_level)
    logger.info(
        "init command started",
        extra={"event": "cli_init_start", "service": settings.app.service_name, "node_id": settings.app.node_id},
    )
    settings.ensure_directories()
    db = get_db(settings)
    db.create_all()
    Path("logs").mkdir(exist_ok=True)
    logger.info(
        "init command completed",
        extra={"event": "cli_init_done", "service": settings.app.service_name, "node_id": settings.app.node_id},
    )
    typer.echo("initialized")


if __name__ == "__main__":
    cli()
