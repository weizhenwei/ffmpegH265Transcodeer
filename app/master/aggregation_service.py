from app.master.job_service import JobService


class AggregationService:
    def __init__(self, job_service: JobService) -> None:
        self.job_service = job_service

    def aggregate(self, job_id: str) -> None:
        self.job_service.refresh_job_status(job_id)
