import socket
from datetime import datetime

from app.core.models import WorkerNode
from app.infra.db import Database


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
                return
            node.capacity = capacity
            node.status = "online"
            node.last_heartbeat_at = datetime.utcnow()
