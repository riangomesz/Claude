"""Contrato de integração com n8n (Tarefa 16). Validadores locais, sem tocar em workflows reais.

Divisão de responsabilidades:
- n8n ORQUESTRA: recebe gatilhos, produz artefatos com as ferramentas locais (ffmpeg, whisper) e envia uma
  missão `ii.mission.v1`; depois lê o resultado `ii.mission_result.v1`.
- ii_mm DECIDE: normaliza, classifica, persiste e devolve estado. Nenhuma regra de classificação vive no n8n.

Segurança:
- Chaves desconhecidas são rejeitadas (contrato fechado); limites de tamanho em listas e textos.
- `uri` de artefato só pode ser caminho RELATIVO dentro do staging compartilhado: sem esquema (http, file),
  sem `..`, sem caminho absoluto ou unidade Windows. Evita leitura arbitrária e SSRF.
- Modelos pagos ficam proibidos por padrão; liberar exige `max_usd > 0` e `approved_by`.
- Assinatura HMAC-SHA256 do corpo, comparada em tempo constante. O segredo nunca entra em log ou resultado.

Idempotência: `mission_id` = hash da referência canônica + estágios + hashes dos artefatos. Um id que não confere
com o conteúdo é rejeitado; reenviar a mesma missão devolve o resultado já registrado.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .contract import canonical_json
from .dedup import IdentityError, canonical_reference_key
from .pipeline import STAGES

MISSION_SCHEMA = "ii.mission.v1"
RESULT_SCHEMA = "ii.mission_result.v1"
ARTIFACT_KINDS = ("transcript", "srt", "scene_candidates", "ffmpeg_scene_stdout", "ffprobe", "frames_manifest",
                  "observations", "visual_metrics", "metadata")
ERROR_CODES = {"VALIDATION_ERROR": False, "MISSING_EVIDENCE": False, "CONFLICT": False, "TRANSIENT": True,
               "BUDGET_DENIED": False}
MAX_ARTIFACTS, MAX_STR = 64, 2048
MAX_BODY_BYTES = 256 * 1024  # missão é metadado; artefatos vão por URI, nunca no corpo
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MISSION_KEYS = {"schema_version", "mission_id", "reference", "requested_stages", "artifacts", "budget", "requested_by", "created_at"}
_REF_KEYS = {"platform", "url", "video_id"}
_ART_KEYS = {"kind", "sha256", "uri", "bytes"}
_BUDGET_KEYS = {"allow_paid_models", "max_usd", "approved_by"}


def _bad_uri(uri: str) -> Optional[str]:
    if not isinstance(uri, str) or not uri or len(uri) > 512:
        return "uri ausente ou longa demais"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", uri):
        return "uri com esquema ou unidade (só caminho relativo ao staging)"
    if uri.startswith(("/", "\\")) or "\\\\" in uri:
        return "uri absoluta"
    parts = re.split(r"[\\/]", uri)
    if any(p == ".." for p in parts):
        return "uri com '..'"
    if any(ord(ch) < 32 for ch in uri):
        return "uri com caractere de controle"
    return None


def compute_mission_id(msg: Dict[str, Any]) -> str:
    ref = msg["reference"]
    key = canonical_reference_key(ref.get("url") or ref.get("video_id"), platform_hint=ref.get("platform"))
    arts = sorted((a["kind"], a["sha256"]) for a in msg.get("artifacts", []))
    payload = canonical_json([key, sorted(msg.get("requested_stages", [])), arts])
    return "ms_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def validate_mission(msg: Any) -> List[str]:
    p: List[str] = []
    if not isinstance(msg, dict):
        return ["missão deve ser objeto JSON"]
    unknown = set(msg) - _MISSION_KEYS
    if unknown:
        p.append(f"chaves desconhecidas: {sorted(unknown)}")
    if msg.get("schema_version") != MISSION_SCHEMA:
        p.append(f"schema_version deve ser {MISSION_SCHEMA}")
    ref = msg.get("reference")
    if not isinstance(ref, dict):
        p.append("reference obrigatório")
    else:
        if set(ref) - _REF_KEYS:
            p.append(f"reference: chaves desconhecidas {sorted(set(ref) - _REF_KEYS)}")
        try:
            canonical_reference_key(ref.get("url") or ref.get("video_id"), platform_hint=ref.get("platform"))
        except IdentityError as exc:
            p.append(f"reference inválida: {exc}")
    stages = msg.get("requested_stages", [])
    if not isinstance(stages, list) or not stages or any(s not in STAGES for s in stages):
        p.append(f"requested_stages deve ser lista não vazia com valores de {STAGES}")
    arts = msg.get("artifacts", [])
    if not isinstance(arts, list) or len(arts) > MAX_ARTIFACTS:
        p.append(f"artifacts deve ser lista com até {MAX_ARTIFACTS} itens")
        arts = []
    for i, a in enumerate(arts):
        if not isinstance(a, dict):
            p.append(f"artifacts[{i}]: não é objeto")
            continue
        if set(a) - _ART_KEYS:
            p.append(f"artifacts[{i}]: chaves desconhecidas {sorted(set(a) - _ART_KEYS)}")
        if a.get("kind") not in ARTIFACT_KINDS:
            p.append(f"artifacts[{i}]: kind inválido {a.get('kind')}")
        if not isinstance(a.get("sha256"), str) or not _SHA.match(a["sha256"]):
            p.append(f"artifacts[{i}]: sha256 inválido")
        why = _bad_uri(a.get("uri"))
        if why:
            p.append(f"artifacts[{i}]: {why}")
    budget = msg.get("budget", {"allow_paid_models": False, "max_usd": 0})
    if not isinstance(budget, dict) or set(budget) - _BUDGET_KEYS:
        p.append("budget inválido")
    elif budget.get("allow_paid_models"):
        if not (isinstance(budget.get("max_usd"), (int, float)) and budget["max_usd"] > 0 and budget.get("approved_by")):
            p.append("modelos pagos exigem max_usd > 0 e approved_by")
    for k in ("requested_by", "created_at"):
        if not isinstance(msg.get(k), str) or not msg[k] or len(msg[k]) > MAX_STR:
            p.append(f"{k} obrigatório (texto até {MAX_STR})")
    if not p:
        expected = compute_mission_id(msg)
        if msg.get("mission_id") != expected:
            p.append(f"mission_id não confere com o conteúdo (esperado {expected})")
    return p


def build_result(mission_id: str, state: str, executed=(), skipped=(), analysis_id: Optional[str] = None,
                 error_code: Optional[str] = None, error_message: Optional[str] = None,
                 provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if error_code is not None and error_code not in ERROR_CODES:
        raise ValueError(f"error_code desconhecido: {error_code}")
    next_action = ("retry" if error_code and ERROR_CODES[error_code] else
                   "human" if error_code in ("CONFLICT", "BUDGET_DENIED") else
                   "provide_evidence" if error_code == "MISSING_EVIDENCE" else
                   "fix_message" if error_code == "VALIDATION_ERROR" else
                   "await_review" if state == "awaiting_review" else "none")
    return {
        "schema_version": RESULT_SCHEMA, "mission_id": mission_id, "state": state,
        "executed": list(executed), "skipped": list(skipped), "analysis_id": analysis_id,
        "error": None if error_code is None else {"code": error_code, "message": (error_message or "")[:500],
                                                  "retryable": ERROR_CODES[error_code]},
        "next_action": next_action, "provenance": provenance or {},
    }


def validate_result(res: Any) -> List[str]:
    p: List[str] = []
    if not isinstance(res, dict) or res.get("schema_version") != RESULT_SCHEMA:
        return [f"resultado deve ser objeto {RESULT_SCHEMA}"]
    if res.get("state") not in STAGES + ("failed", "rejected"):
        p.append(f"state inválido {res.get('state')}")
    err = res.get("error")
    if err is not None and (err.get("code") not in ERROR_CODES or err.get("retryable") != ERROR_CODES[err["code"]]):
        p.append("error incoerente com a tabela de códigos")
    if res["state"] in ("failed", "rejected") and err is None:
        p.append("estado de falha sem error")
    return p


def sign(body: bytes, secret: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, secret: bytes, header: Optional[str]) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(sign(body, secret), header)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MissionGateway:
    """Porta de entrada idempotente: valida, deduplica por mission_id e delega ao executor local."""

    def __init__(self, conn: sqlite3.Connection, executor: Callable[[Dict[str, Any]], Dict[str, Any]], secret: bytes):
        if not secret:
            raise ValueError("segredo HMAC obrigatório")
        self.conn, self.executor, self._secret = conn, executor, secret

    def receive(self, body: bytes, signature: Optional[str]) -> Dict[str, Any]:
        if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_BODY_BYTES:
            return build_result("desconhecida", "rejected", error_code="VALIDATION_ERROR",
                                error_message=f"corpo ausente ou acima do tamanho máximo ({MAX_BODY_BYTES} bytes)")
        if not verify_signature(body, self._secret, signature):
            return build_result("desconhecida", "rejected", error_code="VALIDATION_ERROR", error_message="assinatura inválida")
        try:
            msg = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return build_result("desconhecida", "rejected", error_code="VALIDATION_ERROR", error_message="JSON inválido")
        problems = validate_mission(msg)
        mid = msg.get("mission_id") if isinstance(msg, dict) and isinstance(msg.get("mission_id"), str) else "desconhecida"
        if problems:
            return build_result(mid, "rejected", error_code="VALIDATION_ERROR", error_message="; ".join(problems)[:500])
        row = self.conn.execute("SELECT result_json FROM missions WHERE mission_id = ?", (mid,)).fetchone()
        if row and row["result_json"]:
            prev = json.loads(row["result_json"])
            if not (prev.get("error") or {}).get("retryable"):
                return dict(prev, replayed=True)
        try:
            result = self.executor(msg)
        except Exception as exc:  # não vaza a mensagem (pode conter caminhos locais ou dados privados)
            result = build_result(mid, "failed", error_code="TRANSIENT", error_message=f"erro interno no executor ({exc.__class__.__name__})")
        problems = validate_result(result)
        if problems:
            result = build_result(mid, "failed", error_code="TRANSIENT", error_message="executor devolveu resultado inválido: " + "; ".join(problems))
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("INSERT INTO missions(mission_id, received_at, state, result_json) VALUES (?,?,?,?) "
                              "ON CONFLICT(mission_id) DO UPDATE SET state=excluded.state, result_json=excluded.result_json",
                              (mid, _now(), result["state"], json.dumps(result, ensure_ascii=False)))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return result
