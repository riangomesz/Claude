"""API local do motor criativo (`ii.ce.api.v1`): operações JSON usadas pelo n8n e, no futuro, pelo painel.

Mesmo desenho e mesmas defesas da API do `ii_be` (reutiliza o servidor loopback dele: Host conferido, só `application/json`,
corpo ≤ 256 KiB, sem CORS). Esquema fechado por operação; campo desconhecido é erro. Toda operação de escrita é idempotente
por construção (ids determinísticos), então o n8n pode repetir a chamada sem criar duplicatas.
Decisões humanas (`approve`, `register_review`) recusam atores automáticos, inclusive `n8n:`."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import _be  # noqa: F401
from ii_be.api import MAX_BODY_BYTES, ApiError
from ii_be.engine import Engine
from . import events as EV
from .contracts import APPROVAL_SCOPES, DEPTHS, REVIEW_DECISIONS
from .orchestrator import CEError, CreativeEngine

API_VERSION = "ii.ce.api.v1"
_REF = re.compile(r"^ref_[0-9a-f]{20}$")
_INV = re.compile(r"^inv_[0-9a-f]{20}$")
_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


def _s(name: str, rx=None, n: int = 200, required: bool = True):
    def f(x):
        if not isinstance(x, str) or not x or len(x) > n or (rx and not rx.match(x)):
            raise ApiError("VALIDATION_ERROR", f"{name} inválido")
        return x
    return f


def _opt(fn):
    return lambda x: None if x is None else fn(x)


def _int(name, lo, hi):
    def f(x):
        if not isinstance(x, int) or isinstance(x, bool) or not lo <= x <= hi:
            raise ApiError("VALIDATION_ERROR", f"{name} deve estar entre {lo} e {hi}")
        return x
    return f


def _enum(name, values):
    def f(x):
        if x not in values:
            raise ApiError("VALIDATION_ERROR", f"{name} inválido")
        return x
    return f


def _limits(x):
    if not isinstance(x, dict) or set(x) - {"max_calls", "max_usd", "deadline_s", "require_start_approval"}:
        raise ApiError("VALIDATION_ERROR", "limits inválido")
    return x


REF, INV = _s("reference_id", _REF), _s("investigation_id", _INV)
SPECS: Dict[str, Dict[str, Callable]] = {
    "health": {},
    "open_investigation": {"reference_id": REF, "depth": _opt(_enum("depth", DEPTHS)), "profile_ids": _opt(lambda x: [_s("profile_id", _NAME)(i) for i in x] if isinstance(x, list) and x else (_ for _ in ()).throw(ApiError("VALIDATION_ERROR", "profile_ids inválido"))),
                           "priority": _opt(_int("priority", 1, 9)), "limits": _opt(_limits), "requested_by": _opt(_s("requested_by", n=120))},
    "run_investigation": {"investigation_id": INV, "max_tasks": _opt(_int("max_tasks", 1, 100)), "retry_blocked": _opt(lambda x: x if isinstance(x, bool) else (_ for _ in ()).throw(ApiError("VALIDATION_ERROR", "retry_blocked inválido")))},
    "get_status": {"investigation_id": INV},
    "get_investigation": {"investigation_id": INV},
    "latest_for_reference": {"reference_id": REF},
    "list_open_questions": {"investigation_id": INV},
    "approve": {"investigation_id": INV, "scope": _enum("scope", APPROVAL_SCOPES), "value": _s("value", n=120), "approver": _s("approver", n=120)},
    "register_review": {"reference_id": REF, "key": _s("key", n=100), "decision": _enum("decision", REVIEW_DECISIONS), "reviewer": _s("reviewer", n=120),
                        "note": _opt(_s("note", n=600)), "corrected_value": _opt(_s("corrected_value", n=300))},
    "generate_dossier": {"investigation_id": INV},
    "export_obsidian": {"investigation_id": INV},
    "poll_events": {"consumer": _s("consumer", _NAME), "limit": _opt(_int("limit", 1, 200))},
    "ack_events": {"consumer": _s("consumer", _NAME), "event_ids": lambda x: x if isinstance(x, list) and 0 < len(x) <= 200 and all(isinstance(i, str) and len(i) < 80 for i in x) else (_ for _ in ()).throw(ApiError("VALIDATION_ERROR", "event_ids inválido"))},
}
REQUIRED = {"health": (), "open_investigation": ("reference_id",), "run_investigation": ("investigation_id",), "get_status": ("investigation_id",), "get_investigation": ("investigation_id",),
            "latest_for_reference": ("reference_id",), "list_open_questions": ("investigation_id",), "approve": ("investigation_id", "scope", "value", "approver"),
            "register_review": ("reference_id", "key", "decision", "reviewer"), "generate_dossier": ("investigation_id",), "export_obsidian": ("investigation_id",),
            "poll_events": ("consumer",), "ack_events": ("consumer", "event_ids")}


class CreativeAPI:
    """`factory()` devolve (Engine, CreativeEngine) novos (conexão própria) para cada requisição."""

    def __init__(self, factory: Callable[[], CreativeEngine], out_dir: Path, staging_dir: Path):
        self.factory, self.out_dir, self.staging_dir = factory, Path(out_dir), Path(staging_dir)

    @staticmethod
    def _err(exc: ApiError) -> Dict[str, Any]:
        return {"api": API_VERSION, "ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}

    def handle(self, operation: str, request: Any) -> Dict[str, Any]:
        try:
            if isinstance(request, (bytes, bytearray)):
                if len(request) > MAX_BODY_BYTES:
                    raise ApiError("PAYLOAD_TOO_LARGE", "corpo grande demais")
                try:
                    request = json.loads(request.decode("utf-8")) if request else {}
                except (UnicodeDecodeError, ValueError):
                    raise ApiError("VALIDATION_ERROR", "corpo não é JSON UTF-8 válido") from None
            if not isinstance(request, dict):
                raise ApiError("VALIDATION_ERROR", "requisição deve ser um objeto JSON")
            spec = SPECS.get(operation)
            if spec is None:
                raise ApiError("UNKNOWN_OPERATION", f"operação desconhecida: {operation!r}"[:120])
            extra = set(request) - set(spec)
            if extra:
                raise ApiError("VALIDATION_ERROR", f"campos desconhecidos: {sorted(extra)}"[:200])
            missing = [k for k in REQUIRED[operation] if k not in request]
            if missing:
                raise ApiError("VALIDATION_ERROR", f"campos obrigatórios ausentes: {missing}")
            args = {k: spec[k](v) for k, v in request.items()}
            if operation == "health":
                return {"api": API_VERSION, "ok": True, "data": {"status": "ok"}}
            ce = self.factory()
            try:
                return {"api": API_VERSION, "ok": True, "data": getattr(self, f"op_{operation}")(ce, **args)}
            finally:
                ce.conn.close()
                if ce.engine is not None and ce.engine.conn is not ce.conn:
                    ce.engine.close()
        except ApiError as exc:
            return self._err(exc)
        except KeyError as exc:
            return self._err(ApiError("NOT_FOUND", f"não encontrado: {exc}"[:200]))
        except CEError as exc:
            return self._err(ApiError("VALIDATION_ERROR", str(exc)[:300]))
        except Exception:  # noqa: BLE001 - nunca vaza traceback
            return self._err(ApiError("INTERNAL", "erro interno"))

    # --- operações -------------------------------------------------------------------------------------------------
    def op_open_investigation(self, ce, reference_id, depth="standard", profile_ids=None, priority=5, limits=None, requested_by="n8n:fluxo"):
        out = ce.open_investigation(reference_id, depth=depth, profile_ids=tuple(profile_ids) if profile_ids else ("rian_rocha_ia", "objetaria"), priority=priority, limits=limits, requested_by=requested_by)
        return {k: out[k] for k in ("investigation_id", "reference_id", "seq", "state", "depth", "reference_kind", "created")} | {"tasks": [{"specialist": t["specialist"], "selected": t["selected"], "reason": t["reason"]} for t in out["plan"]["tasks"]]}

    def op_run_investigation(self, ce, investigation_id, max_tasks=None, retry_blocked=False):
        return ce.run(investigation_id, owner="worker:n8n-api", max_tasks=max_tasks, retry_blocked=retry_blocked)

    def op_get_status(self, ce, investigation_id):
        return ce.status(investigation_id)

    def op_get_investigation(self, ce, investigation_id):
        return ce.investigation_object(investigation_id)

    def op_latest_for_reference(self, ce, reference_id):
        iid = ce.latest(reference_id)
        return {"investigation_id": iid}

    def op_list_open_questions(self, ce, investigation_id):
        from .dossier import _Ctx
        from . import analysis as AN
        c = _Ctx(ce, investigation_id)
        tq = [x for t in c.tasks if t["result_json"] for x in json.loads(t["result_json"]).get("questions", [])]
        return {"questions": AN.open_questions(c.inv, c.groups, c.tasks, tq)}

    def op_approve(self, ce, investigation_id, scope, value, approver):
        return ce.approve(investigation_id, scope, value, approver)

    def op_register_review(self, ce, reference_id, key, decision, reviewer, note=None, corrected_value=None):
        return ce.review(reference_id, key, decision, reviewer, note, corrected_value)

    def op_generate_dossier(self, ce, investigation_id):
        r = ce.generate_dossier(investigation_id, self.out_dir)
        return {k: r[k] for k in ("investigation_id", "dossier_version", "created", "content_hash", "sections_without_data")} | {"files": len(r["files"])}

    def op_export_obsidian(self, ce, investigation_id):
        r = ce.export_obsidian(investigation_id, self.staging_dir)
        return {"investigation_id": investigation_id, "notes": len(r["results"]), "related": r["related"]}

    def op_poll_events(self, ce, consumer, limit=50):
        return {"events": [{"event_id": e["event_id"], "type": e["type"], "investigation_id": e["investigation_id"], "payload": e["payload"]} for e in EV.pending(ce.conn, consumer, limit)]}

    def op_ack_events(self, ce, consumer, event_ids):
        from ii_be.db import tx
        with tx(ce.conn) as c:
            for i in event_ids:
                c.execute("INSERT OR IGNORE INTO ce_consumed(consumer, event_id, consumed_at) SELECT ?, event_id, ? FROM ce_events WHERE event_id = ?", (consumer, ce.clock.now(), i))
        return {"acked": len(event_ids)}


def serve(api: CreativeAPI, host: str = "127.0.0.1", port: int = 0):
    """Servidor loopback do `ii_be` reutilizado (só atende 127.0.0.1/::1). Devolve (servidor, thread)."""
    from ii_be.http_local import serve_in_thread
    return serve_in_thread(api, host, port)
