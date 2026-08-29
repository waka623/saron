"""全ての副作用実行を記録する監査ログ(Phase 2 で実装)。誰の承認で・いつ・何を・結果どうなったか。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuditLogEntry:
    proposal_id: str
    action: str
    decided_by: str
    executed_at: datetime
    result: str


def record(entry: AuditLogEntry) -> None:
    raise NotImplementedError("Phase 2 で実装")
