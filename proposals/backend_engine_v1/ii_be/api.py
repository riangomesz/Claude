"""Contratos de API (Tarefa 17): camada de serviços invocáveis, pronta para um painel futuro.

Envelope de resposta `ii.be.api.v1`:
    sucesso: {"api": "ii.be.api.v1", "ok": true, "data": ..., "meta": {"operation": ..., "replayed": bool}}
    erro:    {"api": "ii.be.api.v1", "ok": false, "error": {"code", "message", "details"}}

Códigos: VALIDATION_ERROR, NOT_FOUND, CONFLICT, IDEMPOTENCY_MISMATCH, PAYLOAD_TOO_LARGE, UNKNOWN_OPERATION, BUSY,
INTERNAL (mensagem genérica; nunca rastreamento nem conteúdo interno).

- Requisições são fechadas: campo desconhecido é erro. Tamanho máximo do corpo: 256 KiB. Página máxima: 100.
- Operações que escrevem exigem `idempotency_key`: repetir com o mesmo conteúdo devolve a resposta registrada
  (`replayed: true`); a mesma chave com outro conteúdo é `IDEMPOTENCY_MISMATCH` (proteção contra replay).
- Identificadores são validados por formato antes de qualquer consulta.
- Uma instância por thread: o motor (conexão SQLite) é criado pela fábrica em cada thread que atende requisições.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm.catalog import QueryError
from ii_mm.contract import canonical_json
from .refscope import RefScopedRepository as Repository
from . import artifacts as A
from . import knowledge as K
from .classification import ClassificationService
from .curation import ACTIONS as CURATION_ACTIONS, CurationConflict, CurationError, CurationService
from .db import Busy, tx
from .errors import InvalidInput, ResourceBusy
from .identity import current_metadata
from .search import list_references, search

API_VERSION = "ii.be.api.v1"
MAX_BODY_BYTES = 256 * 1024
MAX_PAGE = 100
_REF = re.compile(r"^ref_[0-9a-f]{20}$")
_JOB = re.compile(r"^job_[0-9a-f]{20}$")
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")
JOB_STATES = ("queued", "claimed", "running", "waiting_dependency", "retry_scheduled", "completed", "failed", "cancelled", "dead_letter")
QUESTIONS = ("teaching_tool", "technique", "visual_element", "techniques_by_level", "mentioned_not_demonstrated", "automation", "transferable")


class ApiError(Exception):
    HTTP = {"VALIDATION_ERROR": 400, "NOT_FOUND": 404, "UNKNOWN_OPERATION": 404, "CONFLICT": 409, "IDEMPOTENCY_MISMATCH": 409,
            "PAYLOAD_TOO_LARGE": 413, "BUSY": 503, "INTERNAL": 500}

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    @property
    def http_status(self) -> int:
        return self.HTTP.get(self.code, 500)


# --------------------------------------------------------------------------- validação declarativa
def _v_ref(x):
    if not isinstance(x, str) or not _REF.match(x):
        raise ApiError("VALIDATION_ERROR", "reference_id inválido")
    return x


def _v_job(x):
    if not isinstance(x, str) or not _JOB.match(x):
        raise ApiError("VALIDATION_ERROR", "job_id inválido")
    return x


def _v_str(n=200):
    def f(x):
        if not isinstance(x, str) or len(x) > n or any(ord(c) < 32 for c in x):
            raise ApiError("VALIDATION_ERROR", f"texto inválido (máx. {n} caracteres, sem controle)")
        return x
    return f


def _v_enum(values):
    def f(x):
        if x not in values:
            raise ApiError("VALIDATION_ERROR", f"valor inválido: {x!r}", {"allowed": list(values)})
        return x
    return f


def _v_bool(x):
    if not isinstance(x, bool):
        raise ApiError("VALIDATION_ERROR", "esperado booleano")
    return x


def _v_limit(x):
    if isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= MAX_PAGE:
        raise ApiError("VALIDATION_ERROR", f"limit deve estar entre 1 e {MAX_PAGE}")
    return x


def _v_dict(x):
    if not isinstance(x, dict):
        raise ApiError("VALIDATION_ERROR", "esperado objeto")
    return x


def _v_list_str(x):
    if not isinstance(x, list) or len(x) > 20 or not all(isinstance(i, str) and len(i) <= 40 for i in x):
        raise ApiError("VALIDATION_ERROR", "esperada lista curta de textos")
    return x


def _v_key(x):
    if not isinstance(x, str) or not _KEY.match(x):
        raise ApiError("VALIDATION_ERROR", "idempotency_key inválida (8 a 100 caracteres [A-Za-z0-9_.:-])")
    return x


def _validate(req: Dict[str, Any], spec: Dict[str, Tuple[Callable, bool]]) -> Dict[str, Any]:
    unknown = set(req) - set(spec)
    if unknown:
        raise ApiError("VALIDATION_ERROR", "campos desconhecidos", {"fields": sorted(unknown)})
    out = {}
    for name, (check, required) in spec.items():
        if name not in req or req[name] is None:
            if required:
                raise ApiError("VALIDATION_ERROR", f"campo obrigatório: {name}")
            continue
        try:
            out[name] = check(req[name])
        except ApiError as exc:
            raise ApiError(exc.code, f"{name}: {exc.message}", exc.details) from None
    return out


WRITE_OPS = {"register_curation", "request_reprocess", "ingest_reference", "register_artifact", "cancel_job", "requeue_job"}
SPECS: Dict[str, Dict[str, Tuple[Callable, bool]]] = {
    "list_references": {"platform": (_v_str(20), False), "text": (_v_str(), False), "analysed": (_v_bool, False),
                        "media": (_v_enum(("available", "missing")), False), "cursor": (_v_str(400), False), "limit": (_v_limit, False)},
    "get_reference": {"reference_id": (_v_ref, True)},
    "get_processing": {"reference_id": (_v_ref, True)},
    "get_evidence": {"reference_id": (_v_ref, True), "status": (_v_enum(("observed_visual", "measured_signal", "transcript_claim",
                                                                       "metadata_claim", "inference", "unverified")), False),
                     "after": (_v_str(80), False), "limit": (_v_limit, False)},
    "get_classification": {"reference_id": (_v_ref, True)},
    "get_curation": {"reference_id": (_v_ref, True)},
    "register_curation": {"reference_id": (_v_ref, True), "action": (_v_enum(CURATION_ACTIONS), True), "reviewer": (_v_str(120), True),
                          "reason": (_v_str(2000), False), "expected_etag": (_v_str(40), False), "params": (_v_dict, False),
                          "idempotency_key": (_v_key, True)},
    "list_jobs": {"state": (_v_enum(JOB_STATES), False), "reference_id": (_v_ref, False), "stage": (_v_str(40), False),
                  "after": (_v_str(80), False), "limit": (_v_limit, False)},
    "get_job": {"job_id": (_v_job, True)},
    "list_failures": {"limit": (_v_limit, False)},
    "request_reprocess": {"reference_id": (_v_ref, True), "stages": (_v_list_str, False), "idempotency_key": (_v_key, True)},
    "search": {"filters": (_v_dict, False), "cursor": (_v_str(400), False), "limit": (_v_limit, False)},
    "search_knowledge": {"question": (_v_enum(QUESTIONS), True), "value": (_v_str(120), False), "include_hypotheses": (_v_bool, False),
                         "limit": (_v_limit, False)},
    "ingest_reference": {"record": (_v_dict, True), "idempotency_key": (_v_key, True)},
    "register_artifact": {"reference_id": (_v_ref, True), "kind": (_v_enum(A.ARTIFACT_KINDS), True), "relpath": (_v_str(240), True),
                          "origin": (_v_str(120), True), "expected_sha256": (_v_str(64), False), "expected_size": (lambda x: x, False),
                          "complete": (_v_bool, False), "idempotency_key": (_v_key, True)},
    "cancel_job": {"job_id": (_v_job, True), "idempotency_key": (_v_key, True)},
    "requeue_job": {"job_id": (_v_job, True), "idempotency_key": (_v_key, True)},
    "diagnostics": {},
}


class ServiceAPI:
    """Com `engine_factory`, cada chamada abre um motor (conexão própria) e o fecha ao final: seguro para o servidor
    HTTP com várias threads. Com `from_engine`, usa o motor dado (uso no mesmo processo e thread)."""

    def __init__(self, engine_factory: Optional[Callable[[], Any]] = None, shared_engine=None):
        if (engine_factory is None) == (shared_engine is None):
            raise ValueError("informe engine_factory OU shared_engine")
        self._factory, self._shared = engine_factory, shared_engine
        self._local = threading.local()

    @classmethod
    def from_engine(cls, engine) -> "ServiceAPI":
        return cls(shared_engine=engine)

    @property
    def engine(self):
        return self._shared if self._shared is not None else self._local.engine

    # ------------------------------------------------------------------ entrada
    def handle(self, operation: str, request: Any) -> Dict[str, Any]:
        if self._shared is not None:
            return self._handle(operation, request)
        try:
            self._local.engine = self._factory()
        except Exception:  # noqa: BLE001
            return self._err(ApiError("INTERNAL", "erro interno"))
        try:
            return self._handle(operation, request)
        finally:
            self._local.engine.close()
            self._local.engine = None

    def _handle(self, operation: str, request: Any) -> Dict[str, Any]:
        try:
            if isinstance(request, (bytes, bytearray)):
                if len(request) > MAX_BODY_BYTES:
                    raise ApiError("PAYLOAD_TOO_LARGE", f"corpo maior que {MAX_BODY_BYTES} bytes")
                try:
                    request = json.loads(request.decode("utf-8")) if request else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ApiError("VALIDATION_ERROR", "corpo não é JSON UTF-8 válido") from None
            if not isinstance(request, dict):
                raise ApiError("VALIDATION_ERROR", "requisição deve ser um objeto JSON")
            if len(canonical_json(request).encode("utf-8")) > MAX_BODY_BYTES:
                raise ApiError("PAYLOAD_TOO_LARGE", f"requisição maior que {MAX_BODY_BYTES} bytes")
            spec = SPECS.get(operation)
            if spec is None:
                raise ApiError("UNKNOWN_OPERATION", f"operação desconhecida: {operation!r}"[:120])
            req = _validate(request, spec)
            if operation in WRITE_OPS:
                return self._idempotent(operation, req)
            return self._ok(operation, getattr(self, f"op_{operation}")(**req))
        except ApiError as exc:
            return self._err(exc)
        except (InvalidInput, QueryError, CurationError, ValueError) as exc:
            code = "CONFLICT" if isinstance(exc, CurationConflict) else "VALIDATION_ERROR"
            return self._err(ApiError(code, " ".join(str(exc).split())[:300]))
        except KeyError:
            return self._err(ApiError("NOT_FOUND", "recurso não encontrado"))
        except (ResourceBusy, Busy):
            return self._err(ApiError("BUSY", "sistema ocupado; tente de novo"))
        except Exception:  # noqa: BLE001 - nunca vaza detalhe interno
            return self._err(ApiError("INTERNAL", "erro interno"))

    def _ok(self, op: str, data: Any, replayed: bool = False) -> Dict[str, Any]:
        return {"api": API_VERSION, "ok": True, "data": data, "meta": {"operation": op, "replayed": replayed}}

    @staticmethod
    def _err(exc: ApiError) -> Dict[str, Any]:
        return {"api": API_VERSION, "ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}

    def _idempotent(self, op: str, req: Dict[str, Any]) -> Dict[str, Any]:
        key = req.pop("idempotency_key")
        rhash = hashlib.sha256(canonical_json({"op": op, "req": req}).encode("utf-8")).hexdigest()
        conn = self.engine.conn
        row = conn.execute("SELECT operation, request_sha256, response_json FROM be_api_requests WHERE idempotency_key = ?", (key,)).fetchone()
        if row:
            if row["request_sha256"] != rhash:
                raise ApiError("IDEMPOTENCY_MISMATCH", "idempotency_key já usada com outro conteúdo")
            return self._ok(op, json.loads(row["response_json"]), replayed=True)
        data = getattr(self, f"op_{op}")(**req)
        with tx(conn) as c:
            c.execute("INSERT OR IGNORE INTO be_api_requests(idempotency_key, operation, request_sha256, response_json, created_at) VALUES (?,?,?,?,?)",
                      (key, op, rhash, json.dumps(data, ensure_ascii=False, sort_keys=True, default=str), self.engine.clock.now()))
        return self._ok(op, data)

    # ------------------------------------------------------------------ helpers
    def _need_ref(self, ref: str) -> sqlite3.Row:
        row = self.engine.conn.execute("SELECT * FROM refs WHERE reference_id = ?", (ref,)).fetchone()
        if row is None:
            raise KeyError(ref)
        return row

    # ------------------------------------------------------------------ operações de leitura
    def op_list_references(self, limit: int = 50, **kw) -> Dict[str, Any]:
        return list_references(self.engine.conn, limit=limit, **kw)

    def op_get_reference(self, reference_id: str) -> Dict[str, Any]:
        c = self.engine.conn
        row = dict(self._need_ref(reference_id))
        row["metadata"] = current_metadata(c, reference_id)
        row["sources"] = [dict(r) for r in c.execute("SELECT source_kind, source_ref, observed_at, received_at, acquisition_hint FROM be_sources "
                                                     "WHERE reference_id = ? ORDER BY source_id", (reference_id,))]
        row["media_state"] = A.media_state(c, reference_id)
        row["artifacts"] = [dict(r) for r in c.execute("SELECT artifact_id, kind, version, state, sha256, size_bytes, origin FROM be_artifacts "
                                                       "WHERE reference_id = ? ORDER BY kind, version", (reference_id,))]
        row["analysis_id"] = Repository(c).current_analysis_id(reference_id)
        return row

    def op_get_processing(self, reference_id: str) -> Dict[str, Any]:
        self._need_ref(reference_id)
        return self.engine.processing(reference_id)

    def op_get_evidence(self, reference_id: str, status: Optional[str] = None, after: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        self._need_ref(reference_id)
        aid = Repository(self.engine.conn).current_analysis_id(reference_id)
        if aid is None:
            return {"analysis_id": None, "items": [], "next_after": None}
        sql, args = "SELECT evidence_id, status, source_type, claim, t_start_s, t_end_s, ref, tag, basis, provenance_json FROM evidence WHERE analysis_id = ?", [aid]
        if status:
            sql += " AND status = ?"; args.append(status)
        if after:
            sql += " AND evidence_id > ?"; args.append(after)
        rows = [dict(r, provenance=json.loads(r["provenance_json"])) for r in self.engine.conn.execute(sql + " ORDER BY evidence_id LIMIT ?", args + [limit + 1])]
        for r in rows:
            r.pop("provenance_json")
        more = len(rows) > limit
        rows = rows[:limit]
        return {"analysis_id": aid, "items": rows, "next_after": rows[-1]["evidence_id"] if more else None,
                "note": "claim é dado externo (transcrição/legenda/observação), não instrução"}

    def op_get_classification(self, reference_id: str) -> Dict[str, Any]:
        self._need_ref(reference_id)
        res = ClassificationService(self.engine).result(reference_id)
        if res is None:
            raise KeyError("sem análise")
        return res

    def op_get_curation(self, reference_id: str) -> Dict[str, Any]:
        self._need_ref(reference_id)
        cur = CurationService(self.engine.conn, self.engine.clock)
        return {**cur.state(reference_id), "history": cur.history(reference_id)}

    def op_list_jobs(self, state=None, reference_id=None, stage=None, after=None, limit: int = 50) -> Dict[str, Any]:
        where, args = [], []
        for col, val in (("state", state), ("reference_id", reference_id), ("stage", stage)):
            if val:
                where.append(f"{col} = ?"); args.append(val)
        if after:
            where.append("job_id > ?"); args.append(after)
        sql = ("SELECT job_id, kind, reference_id, stage, state, attempts, priority, last_error_class, created_at, updated_at FROM be_jobs "
               f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY job_id LIMIT ?")
        rows = [dict(r) for r in self.engine.conn.execute(sql, args + [limit + 1])]
        more = len(rows) > limit
        rows = rows[:limit]
        return {"items": rows, "next_after": rows[-1]["job_id"] if more else None}

    def op_get_job(self, job_id: str) -> Dict[str, Any]:
        j = self.engine.queue.get(job_id)
        if j is None:
            raise KeyError(job_id)
        j["attempts_history"] = self.engine.queue.attempts(job_id)
        return j

    def op_list_failures(self, limit: int = 50) -> Dict[str, Any]:
        rows = [dict(r) for r in self.engine.conn.execute(
            "SELECT job_id, reference_id, stage, state, attempts, last_error_class, last_error, updated_at FROM be_jobs "
            "WHERE state IN ('failed','dead_letter') ORDER BY updated_at DESC, job_id LIMIT ?", (limit,))]
        return {"items": rows, "blocked": self.engine.queue.blocked()[:limit]}

    def op_search(self, filters: Optional[Dict[str, Any]] = None, cursor: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        return search(self.engine.conn, filters or {}, cursor, limit)

    def op_search_knowledge(self, question: str, value: Optional[str] = None, include_hypotheses: bool = False, limit: int = 50) -> Any:
        c = self.engine.conn
        need = {"teaching_tool", "technique", "visual_element"}
        if question in need and not value:
            raise ApiError("VALIDATION_ERROR", f"{question} exige value")
        return {
            "teaching_tool": lambda: K.videos_teaching_tool(c, value, limit),
            "technique": lambda: K.where_technique(c, value, include_hypotheses, limit),
            "visual_element": lambda: K.references_with_visual_element(c, value, limit),
            "techniques_by_level": lambda: K.techniques_by_evidence_level(c),
            "mentioned_not_demonstrated": lambda: K.tools_mentioned_not_demonstrated(c, limit),
            "automation": lambda: K.automation_processes(c, limit),
            "transferable": lambda: K.transferable_knowledge(c, limit),
        }[question]()

    def op_diagnostics(self) -> Dict[str, Any]:
        return self.engine.diagnostics()

    # ------------------------------------------------------------------ operações de escrita
    def op_register_curation(self, reference_id: str, action: str, reviewer: str, reason=None, expected_etag=None, params=None) -> Dict[str, Any]:
        self._need_ref(reference_id)
        params = params or {}
        allowed = {"value", "category", "wrong_name", "right_name", "evidence_id", "technique"}
        if set(params) - allowed:
            raise ApiError("VALIDATION_ERROR", "params desconhecidos", {"fields": sorted(set(params) - allowed)})
        for k, v in params.items():
            _v_str(200)(v)
        return CurationService(self.engine.conn, self.engine.clock).decide(reference_id, action, reviewer, reason, expected_etag, **params)

    def op_request_reprocess(self, reference_id: str, stages: Optional[List[str]] = None) -> Dict[str, Any]:
        self._need_ref(reference_id)
        r = self.engine.plan(reference_id, force=stages or ())
        return {"graph": r.graph, "enqueued": r.enqueued, "reused": r.reused, "already_active": r.already_active}

    def op_ingest_reference(self, record: Dict[str, Any]) -> Dict[str, Any]:
        r = self.engine.ingest(record)
        return {"reference_id": r.reference_id, "canonical_key": r.canonical_key, "created": r.created, "duplicate": r.duplicate,
                "metadata_changed": r.metadata_changed, "media_state": r.media_state, "alias_conflicts": r.alias_conflicts}

    def op_register_artifact(self, reference_id: str, kind: str, relpath: str, origin: str, expected_sha256=None, expected_size=None,
                             complete: bool = True) -> Dict[str, Any]:
        self._need_ref(reference_id)
        if expected_size is not None and (isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0):
            raise ApiError("VALIDATION_ERROR", "expected_size inválido")
        art = self.engine.register_artifact(reference_id, kind, relpath, origin, expected_sha256, expected_size, complete)
        return {k: art[k] for k in ("artifact_id", "kind", "version", "state", "sha256", "size_bytes")}

    def op_cancel_job(self, job_id: str) -> Dict[str, Any]:
        if self.engine.queue.get(job_id) is None:
            raise KeyError(job_id)
        return {"job_id": job_id, "state": self.engine.queue.cancel(job_id)}

    def op_requeue_job(self, job_id: str) -> Dict[str, Any]:
        if self.engine.queue.get(job_id) is None:
            raise KeyError(job_id)
        return {"job_id": job_id, "state": self.engine.queue.requeue(job_id)}
