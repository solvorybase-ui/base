"""Persistence of Product Scout V1 execution results."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence, Any

class CursorLike(Protocol):
    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb): ...
    def execute(self, query: str, params: Sequence[object] | None = None) -> Any: ...
    def fetchone(self) -> Sequence[object] | None: ...
class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...

@dataclass(frozen=True, slots=True)
class PromptVersionRef:
    id: str
    version_identifier: str
    repository_path: str

def get_active_prompt_version(connection: ConnectionLike, *, prompt_key: str = "product_scout") -> PromptVersionRef:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, version_identifier, repository_path
            FROM prompt_versions
            WHERE prompt_key = %s AND is_active = true AND archived_at IS NULL
        """, (prompt_key,))
        row=cursor.fetchone()
    if row is None:
        raise LookupError(f"no active prompt version for {prompt_key!r}")
    return PromptVersionRef(str(row[0]),str(row[1]),str(row[2]))

def create_running_scout_result(connection: ConnectionLike, *, product_variant_id: str, prompt_version_id: str, model_name: str, model_version: str | None = None, automation_run_id: str | None = None) -> str:
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO scout_results (product_variant_id,prompt_version_id,automation_run_id,model_name,model_version,technical_status,started_at)
            VALUES (%s,%s,%s,%s,%s,'running',now()) RETURNING id
        """, (product_variant_id,prompt_version_id,automation_run_id,model_name,model_version))
        row=cursor.fetchone()
    if row is None: raise RuntimeError("scout_result INSERT returned no id")
    return str(row[0])

def finish_scout_success(connection: ConnectionLike, *, scout_result_id: str, decision: str, reason: str) -> None:
    if decision not in {"selected","rejected"}: raise ValueError("invalid Scout decision")
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE scout_results SET technical_status='succeeded', decision=%s, reason=%s,
                finished_at=now(), error_code=NULL, error_summary=NULL, updated_at=now()
            WHERE id=%s
        """, (decision,reason,scout_result_id))

def finish_scout_failure(connection: ConnectionLike, *, scout_result_id: str, technical_status: str, error_code: str, error_summary: str) -> None:
    if technical_status not in {"failed","invalid_output"}: raise ValueError("invalid failure technical_status")
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE scout_results SET technical_status=%s, decision=NULL, reason=NULL,
                finished_at=now(), error_code=%s, error_summary=%s, updated_at=now()
            WHERE id=%s
        """, (technical_status,error_code,error_summary[:1000],scout_result_id))
