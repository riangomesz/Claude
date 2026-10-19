"""Scheduler com grafo de dependências entre etapas (Tarefa 06).

- `StageGraph`: grafo acíclico (detecção de ciclo e ordem topológica de Kahn; dependência desconhecida é erro).
- `Planner.plan(referência)`: decide, por impressão digital (ver `incremental`), quais etapas precisam rodar e
  cria os jobs com as dependências entre eles NUMA transação. Etapa reaproveitável não vira job; seus
  dependentes também não, a menos que alguma entrada deles tenha mudado.
- Jobs de etapa usam `dedup_key = stage|referência|etapa`: replanejar enquanto algo roda não duplica nada.
- Paralelismo: etapas sem dependência entre si (ex.: `transcribe` e `scenes`) ficam prontas ao mesmo tempo e
  podem ser assumidas por workers diferentes, dentro dos limites da fila.
- Reprocessamento seletivo: `force={"classify"}` refaz a etapa ignorando o reuso; as seguintes só refazem se o
  resultado mudar (corte antecipado). `invalidate` marca resultados antigos sem apagá-los.
- `processing_view`: estado de processamento DERIVADO (jobs + resultados), com os nomes do `ii_mm.pipeline`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm.classifier import CLASSIFIER_VERSION
from ii_mm.evidence_rules import CATEGORIES, SUPPORT_LEVELS
from ii_mm.vocabulary import VISUAL_TAGS
from . import artifacts as A
from . import incremental as I
from .db import tx
from .identity import current_metadata
from .queue import ACTIVE, JobQueue


class CycleError(ValueError):
    pass


class StageGraph:
    def __init__(self, deps: Mapping[str, Sequence[str]]):
        self.deps = {s: tuple(d) for s, d in deps.items()}
        unknown = {d for ds in self.deps.values() for d in ds if d not in self.deps}
        if unknown:
            raise ValueError(f"dependências desconhecidas: {sorted(unknown)}")
        self.order = self._toposort()

    def _toposort(self) -> List[str]:
        indeg = {s: len(d) for s, d in self.deps.items()}
        children: Dict[str, List[str]] = {s: [] for s in self.deps}
        for s, ds in self.deps.items():
            for d in ds:
                children[d].append(s)
        ready = sorted(s for s, n in indeg.items() if n == 0)
        out = []
        while ready:
            s = ready.pop(0)
            out.append(s)
            for ch in sorted(children[s]):
                indeg[ch] -= 1
                if indeg[ch] == 0:
                    ready.append(ch)
            ready.sort()
        if len(out) != len(self.deps):
            raise CycleError(f"ciclo entre etapas: {sorted(s for s, n in indeg.items() if n > 0)}")
        return out

    def descendants(self, stages: Iterable[str]) -> List[str]:
        want = set(stages)
        changed = True
        while changed:
            changed = False
            for s, ds in self.deps.items():
                if s not in want and want.intersection(ds):
                    want.add(s)
                    changed = True
        return [s for s in self.order if s in want]


# Etapas audiovisuais (resultados de ferramentas já existentes; nada é reinventado aqui)
MEDIA_GRAPH = StageGraph({
    "acquire": (),                      # descoberta + verificação de integridade da mídia
    "probe": ("acquire",),              # metadados de vídeo (ffprobe)
    "audio": ("acquire",),              # extração de áudio (artefato opcional)
    "transcribe": ("audio",),           # transcrição (whisper/SRT)
    "scenes": ("acquire",),             # detecção de cenas (ffmpeg scene / candidatos)
    "frames": ("scenes",),              # seleção de quadros (manifesto)
    "metrics": ("frames",),             # métricas temporais entre quadros
    "visual_analysis": ("frames",),     # análise visual opcional (observações registradas)
    # evidências + normalização; depende de `acquire` DIRETAMENTE: o SHA-256 da mídia é a identidade de conteúdo no ii_mm
    "assemble": ("acquire", "probe", "transcribe", "scenes", "frames", "metrics", "visual_analysis"),
    "classify": ("assemble",),          # classificação multimodal (ii_mm.Classifier)
    "index": ("classify",),             # índice de conhecimento (com curadoria)
    "export": ("index",),               # nota em staging do Obsidian
})
# Só metadados (sem mídia), quando a duração é conhecida pelos metadados: classifica o que existe, sem inventar.
METADATA_GRAPH = StageGraph({"assemble": (), "classify": ("assemble",), "index": ("classify",), "export": ("index",)})

# Relação com os estados do ii_mm.pipeline (compatibilidade de leitura; ver queue.py)
II_MM_STAGE_OF = {"acquire": "media_available", "probe": "metadata_extracted", "audio": "audio_processed",
                  "transcribe": "audio_processed", "scenes": "visual_processed", "frames": "visual_processed",
                  "metrics": "visual_processed", "visual_analysis": "visual_processed", "assemble": "evidence_normalized",
                  "classify": "classified", "index": "completed", "export": "completed"}

# Artefatos lidos por cada etapa (o primeiro tipo presente vale)
STAGE_ARTIFACTS = {"acquire": ("video",), "probe": ("ffprobe",), "audio": ("audio",), "transcribe": ("transcript_segments", "srt"),
                   "scenes": ("scenes_ffmpeg", "scene_candidates"), "frames": ("frames_manifest",), "metrics": ("frame_metrics",),
                   "visual_analysis": ("observations",)}


def default_taxonomy_version() -> str:
    from ii_mm.text_classifier import RULES
    basis = {"classifier": CLASSIFIER_VERSION, "categories": list(CATEGORIES), "support": list(SUPPORT_LEVELS),
             "tags": sorted(VISUAL_TAGS), "rules": {k: sorted(v.get("strong", [])) for k, v in RULES.items()}}
    return "tax-" + I.digest(basis)[:16]


@dataclass
class EngineConfig:
    taxonomy_version: str = field(default_factory=default_taxonomy_version)
    visual_model: str = "registered_observations"      # quem produziu as observações visuais
    stage_versions: Dict[str, str] = field(default_factory=lambda: {
        "acquire": "1", "probe": "1", "audio": "1", "transcribe": "1", "scenes": "1", "frames": "1", "metrics": "1",
        "visual_analysis": "1", "assemble": "1", "classify": CLASSIFIER_VERSION, "index": "1", "export": "1"})
    stage_priority: Dict[str, int] = field(default_factory=lambda: {"classify": 50, "index": 40, "export": 90})
    stage_timeout_s: Dict[str, float] = field(default_factory=lambda: {"classify": 120.0})
    default_timeout_s: float = 300.0
    max_attempts: int = 5


def curation_digest(conn: sqlite3.Connection, reference_id: str) -> Dict[str, Any]:
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM reviews WHERE reference_id = ?", (reference_id,)).fetchone()[0]
    rev = conn.execute("SELECT COALESCE(MAX(revision), 0) FROM be_curation_log WHERE reference_id = ?", (reference_id,)).fetchone()[0]
    return {"ii_review_seq": int(seq), "be_curation_revision": int(rev)}


def stage_inputs(conn: sqlite3.Connection, reference_id: str, stage: str, graph: StageGraph,
                 upstream: Mapping[str, str], cfg: EngineConfig) -> Dict[str, Any]:
    inputs: Dict[str, Any] = {"upstream": {d: upstream.get(d) for d in graph.deps[stage]}}
    kinds = STAGE_ARTIFACTS.get(stage)
    if kinds:
        art = next((a for a in (A.current(conn, reference_id, k) for k in kinds) if a), None)
        inputs["artifact"] = {"kind": art["kind"], "sha256": art["sha256"]} if art else None
    if stage == "visual_analysis":
        inputs["model"] = cfg.visual_model
    if stage == "assemble":
        meta = current_metadata(conn, reference_id)
        row = conn.execute("SELECT platform, canonical_key, origin_url FROM refs WHERE reference_id = ?", (reference_id,)).fetchone()
        inputs["metadata"] = I.digest(meta)
        inputs["reference"] = dict(row) if row else None
    if stage == "classify":
        inputs["taxonomy"] = cfg.taxonomy_version
    if stage == "index":
        inputs["curation"] = curation_digest(conn, reference_id)
    return inputs


def graph_for(conn: sqlite3.Connection, reference_id: str) -> Tuple[Optional[StageGraph], str]:
    state = A.media_state(conn, reference_id)
    if state == "available":
        return MEDIA_GRAPH, "media"
    if current_metadata(conn, reference_id).get("duration_s"):
        return METADATA_GRAPH, "metadata"
    return None, f"aguardando_midia ({state})"


@dataclass
class PlanResult:
    reference_id: str
    graph: str
    reused: List[str] = field(default_factory=list)
    enqueued: Dict[str, str] = field(default_factory=dict)     # etapa -> job_id
    already_active: List[str] = field(default_factory=list)
    run_id: Optional[str] = None


class Planner:
    def __init__(self, conn: sqlite3.Connection, queue: JobQueue, cfg: Optional[EngineConfig] = None):
        self.conn, self.queue, self.cfg = conn, queue, cfg or EngineConfig()

    def plan(self, reference_id: str, force: Iterable[str] = (), run_id: Optional[str] = None) -> PlanResult:
        graph, gname = graph_for(self.conn, reference_id)
        if graph is None:
            return PlanResult(reference_id, gname)
        force = set(force)
        if force - set(graph.deps):
            raise ValueError(f"etapas desconhecidas em force: {sorted(force - set(graph.deps))}")
        run_id = run_id or "run_" + hashlib.sha256(f"{reference_id}|{self.queue.clock.now()!r}|{sorted(force)}".encode()).hexdigest()[:12]
        result = PlanResult(reference_id, gname, run_id=run_id)
        with tx(self.conn) as c:
            fresh: Dict[str, str] = {}
            to_run: List[str] = []
            for stage in graph.order:
                if stage in force or any(d in to_run for d in graph.deps[stage]):
                    to_run.append(stage)
                    continue
                fp = I.fingerprint(stage, self.cfg.stage_versions[stage], stage_inputs(c, reference_id, stage, graph, fresh, self.cfg))
                hit = I.find_result(c, reference_id, stage, fp)
                if hit:
                    fresh[stage] = hit["output_digest"]
                    result.reused.append(stage)
                else:
                    to_run.append(stage)
            job_of: Dict[str, str] = {}
            for stage in to_run:
                deps = [job_of[d] for d in graph.deps[stage] if d in job_of]
                er = self.queue.enqueue_in(
                    c, "stage", reference_id=reference_id, stage=stage, run_id=run_id,
                    payload={"graph": gname, "force": stage in force},
                    priority=self.cfg.stage_priority.get(stage, 100), dedup_key=f"stage|{reference_id}|{stage}",
                    depends_on=deps, max_attempts=self.cfg.max_attempts)
                job_of[stage] = er.job_id
                if er.created:
                    result.enqueued[stage] = er.job_id
                else:
                    result.already_active.append(stage)
                    if stage in force:  # job já ativo: marca para não reutilizar resultado antigo
                        row = c.execute("SELECT payload_json FROM be_jobs WHERE job_id = ?", (er.job_id,)).fetchone()
                        payload = json.loads(row[0] or "{}")
                        payload["force"] = True
                        c.execute("UPDATE be_jobs SET payload_json = ? WHERE job_id = ?", (json.dumps(payload, sort_keys=True), er.job_id))
        return result


def processing_view(conn: sqlite3.Connection, reference_id: str) -> Dict[str, Any]:
    """Estado derivado por etapa: último job, resultado corrente e o equivalente no `ii_mm.pipeline`."""
    graph, gname = graph_for(conn, reference_id)
    stages = graph.order if graph else []
    out: Dict[str, Any] = {"reference_id": reference_id, "graph": gname, "media_state": A.media_state(conn, reference_id), "stages": {}}
    furthest = "discovered"
    order = ["discovered", "media_available", "metadata_extracted", "audio_processed", "visual_processed", "evidence_normalized",
             "classified", "awaiting_review", "completed"]
    for s in stages:
        job = conn.execute("SELECT job_id, state, attempts, last_error_class, last_error FROM be_jobs WHERE reference_id = ? AND stage = ? "
                           "ORDER BY created_at DESC, rowid DESC LIMIT 1", (reference_id, s)).fetchone()
        res = I.current_result(conn, reference_id, s)
        st = {"job": dict(job) if job else None, "result_digest": res["output_digest"] if res else None,
              "ii_mm_stage": II_MM_STAGE_OF[s]}
        st["status"] = (job["state"] if job and job["state"] in ACTIVE else "done" if res else (job["state"] if job else "not_planned"))
        out["stages"][s] = st
        if st["status"] == "done" and order.index(II_MM_STAGE_OF[s]) > order.index(furthest):
            furthest = II_MM_STAGE_OF[s]
    if furthest in ("classified", "completed"):
        pending = conn.execute("SELECT COUNT(*) FROM review_state WHERE reference_id = ?", (reference_id,)).fetchone()[0] == 0 and \
            conn.execute("SELECT COUNT(*) FROM be_curation WHERE reference_id = ?", (reference_id,)).fetchone()[0] == 0
        out["awaiting_review"] = bool(pending)
    out["ii_mm_equivalent"] = furthest
    return out
