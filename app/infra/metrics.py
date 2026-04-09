class _DummyMetric:
    def labels(self, **kwargs):
        return self

    def inc(self, amount: float = 1.0) -> None:
        return None

    def observe(self, value: float) -> None:
        return None

    def set(self, value: float) -> None:
        return None


try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
except Exception:
    Counter = Gauge = Histogram = None

    def start_http_server(port: int) -> None:
        return None

if Counter is not None:
    job_total = Counter("transcode_job_total", "Job total count", ["status"])
    task_total = Counter("transcode_task_total", "Task total count", ["status"])
    task_duration_seconds = Histogram("transcode_task_duration_seconds", "Task duration")
    queue_depth = Gauge("transcode_queue_depth", "Queue depth")
    worker_online = Gauge("transcode_worker_online", "Online workers")
    retry_total = Counter("transcode_retry_total", "Total retries")
else:
    job_total = _DummyMetric()
    task_total = _DummyMetric()
    task_duration_seconds = _DummyMetric()
    queue_depth = _DummyMetric()
    worker_online = _DummyMetric()
    retry_total = _DummyMetric()


def start_metrics_server(port: int = 9108) -> None:
    start_http_server(port)
