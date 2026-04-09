try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except Exception:
    BlockingScheduler = None
    CronTrigger = None


class SchedulerService:
    def __init__(self) -> None:
        if BlockingScheduler is None:
            raise RuntimeError("apscheduler package is not installed")
        self.scheduler = BlockingScheduler()

    def add_cron_job(self, cron_expr: str, fn: object) -> None:
        trigger = CronTrigger.from_crontab(cron_expr)
        self.scheduler.add_job(fn, trigger=trigger)

    def run(self) -> None:
        self.scheduler.start()
