import logging
import time

from app.infra.metrics import retry_total, task_duration_seconds, task_total
from app.worker.probe_executor import ProbeExecutor
from app.worker.result_reporter import ResultReporter
from app.worker.transcode_executor import TranscodeExecutor

logger = logging.getLogger(__name__)


class WorkerConsumer:
    def __init__(
        self,
        queue: object,
        reporter: ResultReporter,
        probe_executor: ProbeExecutor,
        transcode_executor: TranscodeExecutor,
        worker_id: str,
        task_timeout_sec: int,
        poll_block_ms: int = 5000,
        heartbeat_interval_sec: int = 10,
        heartbeat_fn: object | None = None,
    ) -> None:
        self.queue = queue
        self.reporter = reporter
        self.probe_executor = probe_executor
        self.transcode_executor = transcode_executor
        self.worker_id = worker_id
        self.task_timeout_sec = task_timeout_sec
        self.poll_block_ms = poll_block_ms
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.heartbeat_fn = heartbeat_fn

    def run_forever(self) -> None:
        last_heartbeat = 0.0
        logger.info("worker consumer loop started", extra={"event": "worker_consumer_started", "node_id": self.worker_id})
        while True:
            now = time.time()
            if self.heartbeat_fn is not None and now - last_heartbeat >= self.heartbeat_interval_sec:
                self.heartbeat_fn()
                last_heartbeat = now
                logger.debug("heartbeat sent", extra={"event": "worker_heartbeat_sent", "node_id": self.worker_id})
            messages = self.queue.pop(consumer=self.worker_id, block_ms=self.poll_block_ms, count=1)
            if not messages:
                continue
            for message in messages:
                payload = message.payload
                task_id = payload["task_id"]
                logger.info("task received", extra={"event": "task_received", "node_id": self.worker_id, "task_id": task_id})
                retry_count = int(payload.get("retry_count", 0))
                max_retry = int(payload.get("max_retry", 2))
                self.reporter.mark_running(task_id, self.worker_id)
                ok_probe, probe_result = self.probe_executor.run(payload["input_path"])
                if not ok_probe:
                    should_retry = self.reporter.mark_failure(task_id, probe_result, retry_count + 1, max_retry)
                    if should_retry:
                        retry_total.inc()
                        payload["retry_count"] = retry_count + 1
                        self.queue.push(payload)
                        logger.warning(
                            "probe failed and task requeued",
                            extra={"event": "task_probe_retry", "node_id": self.worker_id, "task_id": task_id},
                        )
                    else:
                        logger.error(
                            "probe failed and task marked failed",
                            extra={"event": "task_probe_failed", "node_id": self.worker_id, "task_id": task_id},
                        )
                    self.queue.ack(message.message_id)
                    task_total.labels(status="FAILED").inc()
                    continue
                result = self.transcode_executor.run(
                    input_path=payload["input_path"],
                    output_path=payload["output_path"],
                    params=payload.get("params", {}),
                    timeout_sec=self.task_timeout_sec,
                )
                if result.ok:
                    self.reporter.mark_success(task_id, probe_result, result.duration_ms)
                    task_total.labels(status="SUCCESS").inc()
                    task_duration_seconds.observe(result.duration_ms / 1000)
                    logger.info(
                        "task transcoded successfully",
                        extra={"event": "task_transcode_success", "node_id": self.worker_id, "task_id": task_id},
                    )
                else:
                    should_retry = self.reporter.mark_failure(task_id, result.stderr, retry_count + 1, max_retry)
                    if should_retry:
                        retry_total.inc()
                        payload["retry_count"] = retry_count + 1
                        self.queue.push(payload)
                        logger.warning(
                            "transcode failed and task requeued",
                            extra={"event": "task_transcode_retry", "node_id": self.worker_id, "task_id": task_id},
                        )
                    else:
                        task_total.labels(status="FAILED").inc()
                        logger.error(
                            "transcode failed and task marked failed",
                            extra={"event": "task_transcode_failed", "node_id": self.worker_id, "task_id": task_id},
                        )
                self.queue.ack(message.message_id)
                logger.debug("message acked", extra={"event": "task_message_acked", "node_id": self.worker_id, "task_id": task_id})
            time.sleep(0.01)
