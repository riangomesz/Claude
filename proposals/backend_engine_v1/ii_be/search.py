"""Busca e recuperação (Tarefa 14), reaproveitando o catálogo do `ii_mm`.

- `search`: usa `ii_mm.catalog.build_sql` (filtros, keyset sobre `idx_refs_created`, análise corrente via CROSS JOIN)
  e ACRESCENTA filtros do backend na mesma cláusula WHERE: texto normalizado dos metadados (`be_terms`), tipo de
  evidência, completude das evidências, triagem/nota da curadoria e intervalo da data de ingestão. A paginação
  continua a do catálogo (cursor estável, sem OFFSET). Se a estrutura do SQL do catálogo mudar, a inserção falha
  alto (teste dedicado), em vez de produzir consulta errada.
- `list_references`: lista TODAS as referências (inclusive sem análise), com estado de mídia e de análise, para o
  painel acompanhar o que ainda está em aquisição.
- Busca vetorial/semântica: NÃO operacional nesta missão. Ver `SemanticIndex` (adaptador opcional, só interface).
"""
from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm._matcher import normalize
from ii_mm.catalog import MAX_PAGE, Query, QueryError, _encode, _value_exists_anywhere, build_sql
from ii_mm.evidence_rules import CATEGORIES

EVIDENCE_STATUSES = ("observed_visual", "measured_signal", "transcript_claim", "metadata_claim", "inference", "unverified")
COMPLETENESS = {"transcript": "transcript_claim", "visual": "observed_visual", "measured": "measured_signal", "metadata": "metadata_claim"}
CURRENT = ("SELECT 1 FROM ref_videos rvx CROSS JOIN analyses ax ON ax.video_pk = rvx.video_pk "
           "JOIN evidence ex ON ex.analysis_id = ax.analysis_id WHERE rvx.reference_id = r.reference_id AND ax.status = 'current'")
_SPLIT = " ORDER BY r.created_at "
QUERY_FIELDS = {"subject", "category", "min_support", "tool", "tool_visual_only", "technique", "technique_level", "platform", "author",
                "evidence_tag", "review_state", "time_range", "descending"}
EXTRA_FIELDS = {"text", "evidence_status", "requires", "triage", "rating", "ingested_from", "ingested_to"}


def _terms(text: str) -> List[str]:
    words = [w for w in normalize(text).split() if len(w) >= 3]
    if not words:
        raise QueryError("texto sem termos pesquisáveis (mínimo 3 letras)")
    return words[:10]


def extra_conditions(f: Dict[str, Any]) -> Tuple[List[str], List[Any]]:
    conds, args = [], []
    if f.get("text"):
        for w in _terms(str(f["text"])):
            conds.append("EXISTS (SELECT 1 FROM be_terms bt WHERE bt.term = ? AND bt.reference_id = r.reference_id)"); args.append(w)
    if f.get("evidence_status"):
        if f["evidence_status"] not in EVIDENCE_STATUSES:
            raise QueryError(f"evidence_status inválido: {f['evidence_status']}")
        conds.append(f"EXISTS ({CURRENT} AND ex.status = ?)"); args.append(f["evidence_status"])
    for req in f.get("requires") or []:
        if req not in COMPLETENESS:
            raise QueryError(f"requires inválido: {req} (use {sorted(COMPLETENESS)})")
        conds.append(f"EXISTS ({CURRENT} AND ex.status = ?)"); args.append(COMPLETENESS[req])
    if f.get("triage"):
        conds.append("EXISTS (SELECT 1 FROM be_curation bc WHERE bc.reference_id = r.reference_id AND bc.triage = ?)"); args.append(f["triage"])
    if f.get("rating"):
        conds.append("EXISTS (SELECT 1 FROM be_curation bc WHERE bc.reference_id = r.reference_id AND bc.rating = ?)"); args.append(f["rating"])
    if f.get("ingested_from"):
        conds.append("r.created_at >= ?"); args.append(str(f["ingested_from"]))
    if f.get("ingested_to"):
        conds.append("r.created_at <= ?"); args.append(str(f["ingested_to"]))
    return conds, args


def to_query(f: Dict[str, Any]) -> Query:
    kw = {k: f[k] for k in QUERY_FIELDS if f.get(k) not in (None, "", [])}
    if "time_range" in kw:
        tr = kw["time_range"]
        if not (isinstance(tr, (list, tuple)) and len(tr) == 2 and all(isinstance(x, (int, float)) for x in tr)):
            raise QueryError("time_range deve ser [início, fim] em segundos")
        kw["time_range"] = (float(tr[0]), float(tr[1]))
    return Query(**kw)


def build(f: Dict[str, Any], cursor: Optional[str], limit: int) -> Tuple[Query, str, List[Any]]:
    unknown = set(f) - QUERY_FIELDS - EXTRA_FIELDS
    if unknown:
        raise QueryError(f"filtros desconhecidos: {sorted(unknown)}")
    q = to_query(f)
    sql, args = build_sql(q, cursor, limit)
    conds, extra = extra_conditions(f)
    if conds:
        parts = sql.split(_SPLIT)
        if len(parts) != 2:
            raise RuntimeError("estrutura do SQL do catálogo do ii_mm mudou; atualizar search.build")
        sql = parts[0] + " AND " + " AND ".join(conds) + _SPLIT + parts[1]
        args = args[:-1] + extra + args[-1:]   # o último argumento do catálogo é o LIMIT
    return q, sql, args


def search(conn: sqlite3.Connection, filters: Dict[str, Any], cursor: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    q, sql, args = build(filters, cursor, limit)
    if not _value_exists_anywhere(conn, q):
        return {"items": [], "next_cursor": None}
    rows = [dict(r) for r in conn.execute(sql, args)]
    has_more = len(rows) > limit
    rows = rows[:limit]
    if rows:
        ids = [r["analysis_id"] for r in rows]
        marks = ",".join("?" * len(ids))
        cats: Dict[str, List[Dict[str, str]]] = {}
        for c in conn.execute(f"SELECT analysis_id, category, support FROM categories WHERE analysis_id IN ({marks}) ORDER BY analysis_id, category", ids):
            cats.setdefault(c["analysis_id"], []).append({"category": c["category"], "support": c["support"]})
        refs = [r["reference_id"] for r in rows]
        cur = {c["reference_id"]: dict(c) for c in conn.execute(
            f"SELECT reference_id, triage, rating FROM be_curation WHERE reference_id IN ({','.join('?' * len(refs))})", refs)}
        for r in rows:
            r["categories"] = sorted(cats.get(r["analysis_id"], []), key=lambda c: CATEGORIES.index(c["category"]))
            r["curation"] = {k: v for k, v in cur.get(r["reference_id"], {}).items() if k != "reference_id"} or None
    nxt = _encode(rows[-1]["created_at"], rows[-1]["reference_id"]) if has_more else None
    return {"items": rows, "next_cursor": nxt}


def _cursor_decode(cursor: str) -> Tuple[str, str]:
    try:
        a, b = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if isinstance(a, str) and isinstance(b, str):
            return a, b
    except Exception:
        pass
    raise QueryError("cursor inválido")


def list_references(conn: sqlite3.Connection, platform: Optional[str] = None, text: Optional[str] = None, analysed: Optional[bool] = None,
                    media: Optional[str] = None, cursor: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    if not 1 <= limit <= MAX_PAGE:
        raise QueryError(f"limit deve estar entre 1 e {MAX_PAGE}")
    where, args = [], []
    if platform:
        where.append("r.platform = ?"); args.append(platform)
    if text:
        for w in _terms(text):
            where.append("EXISTS (SELECT 1 FROM be_terms bt WHERE bt.term = ? AND bt.reference_id = r.reference_id)"); args.append(w)
    has_an = ("EXISTS (SELECT 1 FROM ref_videos rv CROSS JOIN analyses a ON a.video_pk = rv.video_pk "
              "WHERE rv.reference_id = r.reference_id AND a.status = 'current')")
    if analysed is not None:
        where.append(has_an if analysed else f"NOT {has_an}")
    has_media = "EXISTS (SELECT 1 FROM be_artifacts ba WHERE ba.reference_id = r.reference_id AND ba.kind = 'video' AND ba.state = 'verified')"
    if media == "available":
        where.append(has_media)
    elif media == "missing":
        where.append(f"NOT {has_media}")
    elif media is not None:
        raise QueryError("media deve ser 'available' ou 'missing'")
    if cursor:
        ca, rid = _cursor_decode(cursor)
        where.append("(r.created_at, r.reference_id) > (?, ?)"); args += [ca, rid]
    sql = (f"SELECT r.reference_id, r.platform, r.canonical_key, r.origin_url, r.author_handle, r.created_at, {has_an} AS analysed, "
           f"{has_media} AS media_available FROM refs r INDEXED BY idx_refs_created "
           f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY r.created_at, r.reference_id LIMIT ?")
    rows = [dict(r) for r in conn.execute(sql, args + [limit + 1])]
    has_more = len(rows) > limit
    rows = rows[:limit]
    for r in rows:
        r["analysed"], r["media_available"] = bool(r["analysed"]), bool(r["media_available"])
    return {"items": rows, "next_cursor": _encode(rows[-1]["created_at"], rows[-1]["reference_id"]) if has_more else None}


class SemanticIndex:
    """Adaptador OPCIONAL para busca vetorial futura. Não operacional: nenhum embedding é calculado nesta missão.

    Só faria sentido se a busca por termos + facetas não bastar (medir antes no Estágio 2). Implementações futuras
    devem receber apenas texto já armazenado (dado, não instrução) e devolver ids de referência com proveniência."""

    def index(self, reference_id: str, texts: Sequence[str]) -> None:
        raise NotImplementedError("busca semântica não habilitada (proposta, não operacional)")

    def query(self, text: str, limit: int = 20) -> List[str]:
        raise NotImplementedError("busca semântica não habilitada (proposta, não operacional)")
