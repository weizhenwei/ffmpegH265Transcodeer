import socket
import logging
from datetime import datetime

from app.core.models import WorkerNode
from app.infra.db import Database

logger = logging.getLogger(__name__)


class HeartbeatService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def beat(self, worker_id: str, capacity: int) -> None:
        with self.db.session() as session:
            node = session.get(WorkerNode, worker_id)
            if node is None:
                node = WorkerNode(
                    worker_id=worker_id,
                    hostname=socket.gethostname(),
                    capacity=capacity,
                    status="online",
                    last_heartbeat_at=datetime.utcnow(),
                )
                session.add(node)
                logger.info("worker node registered", extra={"event": "worker_registered", "node_id": worker_id})
                return
            node.capacity = capacity
            node.status = "online"
            node.last_heartbeat_at = datetime.utcnow()
            logger.debug("worker heartbeat updated", extra={"event": "worker_heartbeat_updated", "node_id": worker_id})
