"""Processamento incremental com proveniência e versões (Tarefa 09).

Cada etapa tem uma IMPRESSÃO DIGITAL DE ENTRADA:
    sha256(etapa | versão da etapa | entradas)
onde as entradas são: o resumo (`output_digest`) das etapas anteriores, o SHA-256 dos artefatos que a etapa lê e
a configuração que muda o resultado (versão da taxonomia/classificador para `classify`, revisão da curadoria para
`index`, modelo para `visual_analysis`).

- Mesma impressão digital com resultado `valid` = reuso: a etapa não roda de novo.
- Corte antecipado: se uma etapa roda de novo e produz o MESMO `output_digest`, as seguintes continuam válidas.
- Assim, só é recalculado o que depende da informação que mudou:
    transcrição nova   → transcribe, assemble, classify, index, export (frames e cenas reaproveitados)
    taxonomia nova     → classify (e o que vier depois, só se a classificação mudar de fato)
    curadoria humana   → index e export (classificação automática preservada)
    modelo visual novo → visual_analysis e o que depende dela
- Resultados antigos nunca são apagados: `invalidate` marca `invalidated` com o motivo (histórico preservado).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.contract import canonical_json


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def fingerprint(stage: str, stage_version: str, inputs: Dict[str, Any]) -> str:
    return digest({"stage": stage, "version": stage_version, "inputs": inputs})


def find_result(conn: sqlite3.Connection, reference_id: str, stage: str, fp: str) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM be_stage_results WHERE reference_id = ? AND stage = ? AND fingerprint = ? AND status = 'valid'",
                     (reference_id, stage, fp)).fetchone()
    return _row(r)


def current_result(conn: sqlite3.Connection, reference_id: str, stage: str) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM be_stage_results WHERE reference_id = ? AND stage = ? AND status = 'valid' "
                     "ORDER BY created_at DESC, rowid DESC LIMIT 1", (reference_id, stage)).fetchone()
    return _row(r)


def _row(r) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    out = dict(r)
    out["result"] = json.loads(out.pop("result_json"))
    return out


def record_result(conn: sqlite3.Connection, reference_id: str, stage: str, fp: str, output_digest: str,
                  result: Dict[str, Any], stage_version: str, job_id: Optional[str], now: float) -> None:
    """Grava (dentro da transação de conclusão do job). Uma impressão digital = um resultado; reescrever
    a mesma é idempotente e reativa um resultado invalidado."""
    if not conn.in_transaction:
        raise RuntimeError("record_result exige a transação de conclusão do job")
    conn.execute("INSERT INTO be_stage_results(reference_id, stage, fingerprint, output_digest, result_json, stage_version, job_id, status, created_at) "
                 "VALUES (?,?,?,?,?,?,?, 'valid', ?) ON CONFLICT(reference_id, stage, fingerprint) DO UPDATE SET "
                 "output_digest=excluded.output_digest, result_json=excluded.result_json, job_id=excluded.job_id, status='valid', "
                 "created_at=excluded.created_at, invalidated_reason=NULL",
                 (reference_id, stage, fp, output_digest, json.dumps(result, ensure_ascii=False, sort_keys=True), stage_version, job_id, now))


def invalidate(conn: sqlite3.Connection, reference_id: str, stages: Iterable[str], reason: str) -> int:
    if not conn.in_transaction:
        raise RuntimeError("invalidate exige transação aberta")
    stages = list(stages)
    if not stages:
        return 0
    cur = conn.execute(f"UPDATE be_stage_results SET status='invalidated', invalidated_reason=? WHERE reference_id = ? AND status='valid' "
                       f"AND stage IN ({','.join('?' * len(stages))})", (reason[:300], reference_id, *stages))
    return cur.rowcount


def history(conn: sqlite3.Connection, reference_id: str, stage: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM be_stage_results WHERE reference_id = ?"
    args: list = [reference_id]
    if stage:
        sql += " AND stage = ?"
        args.append(stage)
    return [_row(r) for r in conn.execute(sql + " ORDER BY created_at, rowid", args)]
