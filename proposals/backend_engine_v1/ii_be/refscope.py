"""Análise corrente POR REFERÊNCIA sobre o repositório do `ii_mm` (mitigação da incompatibilidade I1).

No `ii_mm`, a análise corrente é por VÍDEO (`analyses.status = 'current'` por `video_pk`). Quando o mesmo arquivo é
publicado em duas referências (ex.: Instagram e YouTube), a classificação da segunda supera a da primeira, e
`Repository.current_analysis_id(primeira)` passa a devolver o documento da OUTRA publicação (com legenda e
metadados dela). Reproduzido em `tests/test_shared_media.py`.

Sem alterar a RC1, o backend usa `RefScopedRepository`: `current_analysis_id(ref)` devolve a análise mais recente
cujo documento pertence à referência (`reference.reference_id` ou `original_reference_id`), com retorno ao
comportamento do `ii_mm` quando não houver. `ReviewService(RefScopedRepository(conn))` passa a revisar e sobrepor
a análise certa. Limitação que permanece: os filtros do catálogo do `ii_mm` (SQL) continuam olhando a análise
corrente do vídeo; as perguntas de conhecimento do backend (`be_knowledge`) usam a análise da referência.
"""
from __future__ import annotations

import json
from typing import Optional

from . import _ii_mm  # noqa: F401
from ii_mm.db.repository import Repository
from ii_mm.review import ReviewService


class RefScopedRepository(Repository):
    def current_analysis_id(self, reference_id: str) -> Optional[str]:
        needle = json.dumps(reference_id)  # pré-filtro barato; a confirmação é feita no JSON decodificado
        rows = self.conn.execute(
            "SELECT a.analysis_id, a.document_json FROM ref_videos rv CROSS JOIN analyses a ON a.video_pk = rv.video_pk "
            "WHERE rv.reference_id = ? AND instr(a.document_json, ?) > 0 ORDER BY a.created_at DESC, a.analysis_id DESC",
            (reference_id, needle)).fetchall()
        for r in rows:
            ref = json.loads(r["document_json"]).get("reference") or {}
            if reference_id in (ref.get("reference_id"), ref.get("original_reference_id")):
                return r["analysis_id"]
        return super().current_analysis_id(reference_id)


def repository(conn) -> RefScopedRepository:
    return RefScopedRepository(conn)


def review_service(conn) -> ReviewService:
    return ReviewService(RefScopedRepository(conn))
