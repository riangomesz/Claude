"""Reconciliação: agrupa afirmações por chave e calcula o estado de verificação a partir das EVIDÊNCIAS, não do número de agentes.

Regras (nesta ordem): valores divergentes → `contradicted` (aberto); só hipótese/recomendação/pergunta → `hypothesis`;
evidência visual/medida → `supported` (técnicas de movimento sem sequência temporal → `supported_static`); só fala/legenda →
`claimed`; só inferência → `hypothesis`; nada → `unverified`. Concordância entre agentes é registrada e NÃO muda o estado.
A decisão humana (ce_reviews, por referência+chave) é aplicada por cima e preservada entre versões da investigação.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from . import _be  # noqa: F401
from ii_be.db import tx
from .contracts import MOTION_TECHNIQUES, SAID_STATUS, STATUS_RANK, STRONG_STATUS, VERIFICATION
from .evidence import ev_index

HUMAN_STATE = {"confirm": "confirmed", "reject": "rejected", "needs_evidence": "needs_evidence", "correct": "corrected"}


def latest_reviews(conn: sqlite3.Connection, reference_id: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in conn.execute("SELECT * FROM ce_reviews WHERE reference_id = ? ORDER BY review_id", (reference_id,)):
        out[r["key"]] = dict(r)
    return out


def reconcile(conn: sqlite3.Connection, investigation_id: str, bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    ev = ev_index(bundle)
    levels = {t["technique"]: t.get("level") for t in bundle["facets"].get("techniques", [])}
    reviews = latest_reviews(conn, bundle["reference_id"])
    rows = [dict(r) for r in conn.execute("SELECT * FROM ce_claims WHERE investigation_id = ? ORDER BY claim_id", (investigation_id,))]
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault(r["key"], []).append(r)
    groups = []
    for key in sorted(by_key):
        cl = by_key[key]
        values = sorted({c["value"] for c in cl})
        agents = sorted({c["specialist"] for c in cl})
        ids = sorted({i for c in cl for i in json.loads(c["evidence_ids_json"])})
        statuses = [ev[i]["status"] for i in ids if i in ev]
        strongest = min(statuses, key=lambda s: STATUS_RANK.get(s, 9)) if statuses else None
        kinds = {c["kind"] for c in cl}
        conflict = len(values) > 1
        if conflict:
            state = "contradicted"
        elif kinds <= {"hypothesis", "recommendation", "question"}:
            state = "hypothesis"
        elif strongest in STRONG_STATUS:
            state = "supported"
            tech = key.split(":", 1)[1] if key.startswith("tecnica:") else None
            if tech in MOTION_TECHNIQUES and levels.get(tech) != "temporal_sequence":
                state = "supported_static"
        elif strongest in SAID_STATUS:
            state = "claimed"
        elif strongest == "inference":
            state = "hypothesis"
        else:
            state = "unverified"
        best = sorted(cl, key=lambda c: (STATUS_RANK.get(min((ev[i]["status"] for i in json.loads(c["evidence_ids_json"]) if i in ev), key=lambda s: STATUS_RANK.get(s, 9), default="unverified"), 9), c["claim_id"]))[0]
        rv = reviews.get(key)
        summary = best["statement"]
        if conflict:
            summary = " | ".join(f"{c['specialist']}: {c['statement']}" for c in cl)[:600]
        elif len(agents) > 1:
            summary += f" ({len(agents)} especialistas concordam; concordância não eleva o estado)"
        groups.append({"key": key, "domain": best["domain"], "kind": sorted(kinds)[0], "state": state, "human_state": HUMAN_STATE[rv["decision"]] if rv else None,
                       "strongest_status": strongest, "agents": agents, "claim_ids": [c["claim_id"] for c in cl], "evidence_ids": ids,
                       "values": values, "conflict": conflict, "summary": summary, "human_note": (rv or {}).get("note"), "corrected_value": (rv or {}).get("corrected_value")})
    with tx(conn) as c:
        c.execute("DELETE FROM ce_groups WHERE investigation_id = ?", (investigation_id,))
        for g in groups:
            c.execute("INSERT INTO ce_groups(investigation_id, key, domain, kind, state, human_state, strongest_status, agents_json, claim_ids_json, "
                      "evidence_ids_json, values_json, conflict, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (investigation_id, g["key"], g["domain"], g["kind"], g["state"], g["human_state"], g["strongest_status"], json.dumps(g["agents"]),
                       json.dumps(g["claim_ids"]), json.dumps(g["evidence_ids"]), json.dumps(g["values"]), int(g["conflict"]), g["summary"]))
    return groups


def load_groups(conn: sqlite3.Connection, investigation_id: str) -> List[Dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM ce_groups WHERE investigation_id = ? ORDER BY key", (investigation_id,)):
        out.append({"key": r["key"], "domain": r["domain"], "kind": r["kind"], "state": r["state"], "human_state": r["human_state"],
                    "strongest_status": r["strongest_status"], "agents": json.loads(r["agents_json"]), "claim_ids": json.loads(r["claim_ids_json"]),
                    "evidence_ids": json.loads(r["evidence_ids_json"]), "values": json.loads(r["values_json"]), "conflict": bool(r["conflict"]), "summary": r["summary"]})
    return out
