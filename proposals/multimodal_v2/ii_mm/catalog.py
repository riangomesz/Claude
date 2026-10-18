"""Catálogo pesquisável com paginação por cursor (Tarefa 13).

- Consulta SEMPRE a análise corrente de cada referência.
- Filtros combináveis (AND): assunto (termos), categoria (+ apoio mínimo), ferramenta (+ só visual),
  técnica (+ nível), plataforma, autor (metadado), tag de evidência, status de revisão, intervalo temporal.
- Paginação por cursor (keyset) sobre (created_at, reference_id): ordem estável, custo por página
  independente da posição, sem OFFSET e sem carregar o catálogo em memória.
- Uma consulta para a página + uma para o resumo de categorias da página (sem N+1).
"""
from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ._matcher import normalize
from .evidence_rules import CATEGORIES, SUPPORT_LEVELS

MAX_PAGE = 200


class QueryError(ValueError):
    pass


@dataclass
class Query:
    subject: Optional[str] = None
    category: Optional[str] = None
    min_support: Optional[str] = None
    tool: Optional[str] = None
    tool_visual_only: bool = False
    technique: Optional[str] = None
    technique_level: Optional[str] = None
    platform: Optional[str] = None
    author: Optional[str] = None
    evidence_tag: Optional[str] = None
    review_state: Optional[str] = None      # pending | accepted | rejected | added (para a categoria filtrada)
    time_range: Optional[Tuple[float, float]] = None  # evidência que intersecta [a, b]
    descending: bool = False


@dataclass
class Page:
    items: List[Dict[str, Any]]
    next_cursor: Optional[str]
    sql: str = field(repr=False, default="")


def _encode(created_at: str, reference_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at, reference_id]).encode()).decode()


def _decode(cursor: str) -> Tuple[str, str]:
    try:
        a, b = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if not (isinstance(a, str) and isinstance(b, str)):
            raise ValueError
        return a, b
    except Exception:
        raise QueryError("cursor inválido") from None


def build_sql(q: Query, cursor: Optional[str], limit: int) -> Tuple[str, List[Any]]:
    """Percorre `refs` na ordem do índice (created_at, reference_id); filtros da análise corrente num EXISTS."""
    if not 1 <= limit <= MAX_PAGE:
        raise QueryError(f"limit deve estar entre 1 e {MAX_PAGE}")
    ref_where, ref_args = [], []          # condições sobre refs / review_state
    an_where, an_args = [], []            # condições sobre a análise corrente (alias a)
    if q.platform:
        ref_where.append("r.platform = ?"); ref_args.append(q.platform)
    if q.author:
        ref_where.append("r.author_handle = ?"); ref_args.append(q.author)
    if q.subject:
        words = [w for w in normalize(q.subject).split() if len(w) >= 3]
        if not words:
            raise QueryError("assunto sem termos pesquisáveis (mínimo 3 letras)")
        for w in words:
            an_where.append("EXISTS (SELECT 1 FROM search_terms s WHERE s.term = ? AND s.analysis_id = a.analysis_id)"); an_args.append(w)
    if q.category:
        if q.category not in CATEGORIES:
            raise QueryError(f"categoria desconhecida: {q.category}")
        allowed = list(SUPPORT_LEVELS)
        if q.min_support:
            if q.min_support not in SUPPORT_LEVELS:
                raise QueryError(f"min_support inválido: {q.min_support}")
            allowed = list(SUPPORT_LEVELS[: SUPPORT_LEVELS.index(q.min_support) + 1])
        marks = ",".join("?" * len(allowed))
        an_where.append(f"EXISTS (SELECT 1 FROM categories c WHERE c.analysis_id = a.analysis_id AND c.category = ? AND c.support IN ({marks}))")
        an_args += [q.category] + allowed
    if q.review_state:
        if not q.category:
            raise QueryError("review_state exige category")
        if q.review_state == "pending":
            ref_where.append("NOT EXISTS (SELECT 1 FROM review_state rs WHERE rs.reference_id = r.reference_id AND rs.target = ?)")
            ref_args.append(f"category:{q.category}")
        else:
            ref_where.append("EXISTS (SELECT 1 FROM review_state rs WHERE rs.reference_id = r.reference_id AND rs.target = ? AND rs.state = ?)")
            ref_args += [f"category:{q.category}", q.review_state]
    if q.tool:
        cond = " AND t.status = 'visually_identified'" if q.tool_visual_only else ""
        an_where.append(f"EXISTS (SELECT 1 FROM tools t WHERE t.analysis_id = a.analysis_id AND t.name = ?{cond})"); an_args.append(q.tool)
    if q.technique:
        lvl = " AND tq.level = ?" if q.technique_level else ""
        an_where.append(f"EXISTS (SELECT 1 FROM techniques tq WHERE tq.analysis_id = a.analysis_id AND tq.technique = ?{lvl})")
        an_args += [q.technique] + ([q.technique_level] if q.technique_level else [])
    if q.evidence_tag or q.time_range:
        conds, eargs = ["e.analysis_id = a.analysis_id"], []
        if q.evidence_tag:
            conds.append("e.tag = ?"); eargs.append(q.evidence_tag)
        if q.time_range:
            t0, t1 = q.time_range
            if t1 < t0:
                raise QueryError("intervalo temporal invertido")
            conds.append("e.t_start_s IS NOT NULL AND e.t_start_s <= ? AND COALESCE(e.t_end_s, e.t_start_s) >= ?"); eargs += [t1, t0]
        an_where.append(f"EXISTS (SELECT 1 FROM evidence e WHERE {' AND '.join(conds)})"); an_args += eargs
    # CROSS JOIN força a ordem ref_videos -> analyses. Com JOIN comum o planner varria todas as análises
    # correntes por referência (idx_analyses_current só com status=?), um custo O(N²) visto no benchmark.
    current = ("SELECT a.analysis_id FROM ref_videos rv CROSS JOIN analyses a ON a.video_pk = rv.video_pk "
               "WHERE rv.reference_id = r.reference_id AND a.status = 'current'")
    where, args = [f"EXISTS ({current}{''.join(' AND ' + w for w in an_where)})"], list(an_args)
    where += ref_where
    args += ref_args
    op, order = ("<", "DESC") if q.descending else (">", "ASC")
    if cursor:
        ca, rid = _decode(cursor)
        where.append(f"(r.created_at, r.reference_id) {op} (?, ?)"); args += [ca, rid]
    sql = ("SELECT r.reference_id, r.platform, r.author_handle, r.subject, r.created_at, "
           f"({current.replace('SELECT a.analysis_id', 'SELECT MAX(a.analysis_id)', 1)}) AS analysis_id "
           f"FROM refs r INDEXED BY idx_refs_created WHERE {' AND '.join(where)} "
           f"ORDER BY r.created_at {order}, r.reference_id {order} LIMIT ?")
    return sql, args + [limit + 1]


def search(conn: sqlite3.Connection, q: Query, cursor: Optional[str] = None, limit: int = 50) -> Page:
    sql, args = build_sql(q, cursor, limit)
    rows = [dict(r) for r in conn.execute(sql, args)]
    has_more = len(rows) > limit
    rows = rows[:limit]
    if rows:
        ids = [r["analysis_id"] for r in rows]
        marks = ",".join("?" * len(ids))
        cats: Dict[str, List[Dict[str, str]]] = {}
        for c in conn.execute(f"SELECT analysis_id, category, support FROM categories WHERE analysis_id IN ({marks}) "
                              "ORDER BY analysis_id, category", ids):
            cats.setdefault(c["analysis_id"], []).append({"category": c["category"], "support": c["support"]})
        for r in rows:
            r["categories"] = sorted(cats.get(r["analysis_id"], []), key=lambda c: CATEGORIES.index(c["category"]))
    nxt = _encode(rows[-1]["created_at"], rows[-1]["reference_id"]) if has_more else None
    return Page(rows, nxt, sql)


def iterate(conn: sqlite3.Connection, q: Query, page_size: int = 100):
    """Percorre o resultado inteiro página por página (memória limitada a uma página)."""
    cursor = None
    while True:
        page = search(conn, q, cursor, page_size)
        yield from page.items
        if not page.next_cursor:
            return
        cursor = page.next_cursor


def explain(conn: sqlite3.Connection, q: Query) -> List[str]:
    sql, args = build_sql(q, None, 10)
    return [r[-1] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, args)]
