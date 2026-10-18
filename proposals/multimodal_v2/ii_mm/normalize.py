"""Normalização de evidências de fontes heterogêneas num documento `ii.reference_analysis.v2` (Tarefa 03).

Garantias:
- Cada evidência guarda a fonte original (provenance.source + extractor + artefato).
- Transcrição e metadados NUNCA viram `observed_visual` (o contrato também barra isso).
- A base visual é derivada do número de frames citados; uma alegação de base mais forte é rebaixada.
- Observação de movimento sustentada só por 1 ou 2 quadros vira `inference`, com motivo registrado.
- A mesma evidência vinda duas vezes é consolidada (ID por conteúdo), sem perder a segunda origem.
- Entrada malformada é rejeitada no relatório, nunca levanta exceção.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .adapters import AdapterResult
from .contract import TIME_TOLERANCE_S, empty_document, make_evidence
from .vocabulary import VISUAL_TAGS

MOTION_TAG_PREFIXES = ("motion_", "animated_", "camera_move")
BASIS_ORDER = ("static_frame", "frame_pair", "frame_sequence", "video_clip")


def is_motion_tag(tag: str) -> bool:
    """Tags do vocabulário usam o flag `motion`; tags desconhecidas com prefixo de movimento também contam."""
    spec = VISUAL_TAGS.get(tag)
    return spec.motion if spec else tag.startswith(MOTION_TAG_PREFIXES)


class Normalizer:
    def __init__(self, reference_id: str, platform: str, video_id: str, duration_s: float,
                 content_sha256: Optional[str] = None, origin_url: Optional[str] = None,
                 author_handle: Optional[str] = None):
        self.doc = empty_document(reference_id, platform, video_id, duration_s, content_sha256, origin_url, author_handle)
        self.video_key = content_sha256 or f"{platform}:{video_id}"
        self.duration = float(duration_s)
        self._ev: Dict[str, Dict[str, Any]] = {}
        self._frames: Dict[str, Dict[str, Any]] = {}
        self.report: Dict[str, Any] = {"accepted": 0, "merged_duplicates": 0, "rejected": [], "downgraded": [],
                                       "adapter_errors": []}

    # -- utilidades -------------------------------------------------------
    def _in_range(self, *ts: Optional[float]) -> bool:
        return all(t is None or 0 <= t <= self.duration + TIME_TOLERANCE_S for t in ts)

    def _reject(self, what: str, why: str) -> None:
        self.report["rejected"].append(f"{what}: {why}")

    def _adapter(self, res: AdapterResult) -> None:
        self.report["adapter_errors"].extend(f"[{res.kind}] {e}" for e in res.errors)

    def _add(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        cur = self._ev.get(ev["evidence_id"])
        if cur is None:
            self._ev[ev["evidence_id"]] = ev
            self.report["accepted"] += 1
            return ev
        self.report["merged_duplicates"] += 1
        other = ev["provenance"]
        if other != cur["provenance"]:
            also = cur["provenance"].setdefault("also_from", [])
            if other not in also:
                also.append(other)
        return cur

    # -- fontes -----------------------------------------------------------
    def add_transcript(self, res: AdapterResult, extractor: str = "whisper") -> List[str]:
        self._adapter(res)
        ids = []
        known = {s["segment_id"] for s in self.doc["transcript"]}
        for seg in res.records:
            if not self._in_range(seg["t_start_s"], seg["t_end_s"]):
                self._reject(f"segmento {seg['segment_id']}", "fora da duração do vídeo")
                continue
            if seg["segment_id"] in known:
                self._reject(f"segmento {seg['segment_id']}", "segment_id já registrado")
                continue
            known.add(seg["segment_id"])
            self.doc["transcript"].append(dict(seg))
            ev = self._add(make_evidence(
                self.video_key, status="transcript_claim", source_type="whisper", claim=seg["text"],
                t_start_s=seg["t_start_s"], t_end_s=seg["t_end_s"], ref=seg["segment_id"],
                provenance={"source": res.source.get("source", "transcription"), "extractor": extractor,
                            "untrusted_text": True}))
            ids.append(ev["evidence_id"])
        return ids

    def add_frames(self, res: AdapterResult) -> None:
        self._adapter(res)
        for f in res.records:
            if not self._in_range(f["t_s"]):
                self._reject(f"frame {f['frame_id']}", "fora da duração do vídeo")
                continue
            if f["frame_id"] in self._frames:
                if self._frames[f["frame_id"]]["sha256"] != f["sha256"]:
                    self._reject(f"frame {f['frame_id']}", "mesmo ID com SHA-256 diferente (conflito)")
                continue
            rec = {k: f[k] for k in ("frame_id", "t_s", "sha256", "file", "width", "height", "role", "pair_with") if f.get(k) is not None}
            self._frames[f["frame_id"]] = rec
            self.doc["frames"].append(rec)

    def add_scene_candidates(self, res: AdapterResult) -> List[str]:
        """Candidatos de corte = medição; NÃO são prova de técnica de edição."""
        self._adapter(res)
        ids = []
        for c in res.records:
            if not self._in_range(c["t_s"]):
                self._reject(f"cena t={c['t_s']}", "fora da duração do vídeo")
                continue
            ev = self._add(make_evidence(
                self.video_key, status="measured_signal", source_type="scene_detection",
                claim=f"candidato a mudança de cena (score {c['score']})", t_start_s=c["t_s"], tag="scene_candidate",
                provenance={"source": res.source.get("source", "scene_detection"),
                            "threshold": res.source.get("threshold")},
                extra={"score": c["score"]}))
            ids.append(ev["evidence_id"])
        return ids

    def add_probe(self, res: AdapterResult) -> Optional[str]:
        self._adapter(res)
        if not res.records:
            return None
        p = res.records[0]
        if abs(p["duration_s"] - self.duration) > TIME_TOLERANCE_S:
            self._reject("probe", f"duração do ffprobe ({p['duration_s']}) diverge da declarada ({self.duration})")
            return None
        self.doc["video"].update({k: p[k] for k in ("width", "height", "fps", "has_audio") if p.get(k) is not None})
        self.doc["metrics"].append({"name": "probe", "value": dict(p), "provenance": {"source": "ffprobe"}})
        ev = self._add(make_evidence(
            self.video_key, status="measured_signal", source_type="ffprobe",
            claim=f"{p['width']}x{p['height']} @ {p['fps']} fps, {p['duration_s']} s", t_start_s=0.0,
            t_end_s=min(p["duration_s"], self.duration), tag="probe", provenance={"source": "ffprobe"}))
        return ev["evidence_id"]

    def add_visual_metrics(self, res: AdapterResult) -> List[str]:
        self._adapter(res)
        ids = []
        for m in res.records:
            if not self._in_range(m["t_start_s"], m["t_end_s"]):
                self._reject(f"métrica {m['t_start_s']}-{m['t_end_s']}", "fora da duração do vídeo")
                continue
            ev = self._add(make_evidence(
                self.video_key, status="measured_signal", source_type="visual_metric",
                claim="diferença visual entre dois instantes: " + ", ".join(f"{k}={v}" for k, v in sorted(m["metrics"].items())),
                t_start_s=m["t_start_s"], t_end_s=m["t_end_s"], tag="frame_difference_metric",
                provenance={"source": res.source.get("source")}, extra={"metrics": m["metrics"]}))
            ids.append(ev["evidence_id"])
        return ids

    def add_metadata(self, caption: Optional[str] = None, hashtags: Sequence[str] = (),
                     source: str = "instagram_metadata") -> List[str]:
        ids = []
        for field_name, value in (("caption", caption), ("hashtags", " ".join(h for h in hashtags if h))):
            if value and str(value).strip():
                ev = self._add(make_evidence(
                    self.video_key, status="metadata_claim", source_type="instagram_metadata",
                    claim=" ".join(str(value).split()), ref=field_name, provenance={"source": source, "field": field_name}))
                ids.append(ev["evidence_id"])
        return ids

    def add_observations(self, res: AdapterResult) -> List[str]:
        self._adapter(res)
        ids = []
        for o in res.records:
            frames = [self._frames.get(r) for r in o["frame_refs"]]
            if any(f is None for f in frames):
                self._reject(f"observação '{o['tag']}' em {o['frame_refs']}", "frame citado não está registrado (sem artefato verificável)")
                continue
            if not self._in_range(o["t_s"]):
                self._reject(f"observação '{o['tag']}'", "t_s fora da duração")
                continue
            derived = BASIS_ORDER[min(len(frames), 3) - 1]
            claimed = o.get("basis")
            basis = derived
            if claimed in BASIS_ORDER and BASIS_ORDER.index(claimed) > BASIS_ORDER.index(derived):
                self.report["downgraded"].append(f"'{o['tag']}': base alegada {claimed} rebaixada para {derived} (só {len(frames)} frame(s))")
            elif claimed in BASIS_ORDER:
                basis = claimed
            status = "observed_visual" if o["kind"] == "observation" else "inference"
            t_vals = sorted(f["t_s"] for f in frames)
            source_type = "human_observation" if o["observer"].startswith("human:") else "agent_observation"
            prov = {"source": res.source.get("source"), "observer": o["observer"], "artifact_sha256": frames[0]["sha256"],
                    "frame_refs": list(o["frame_refs"]), "frame_sha256s": [f["sha256"] for f in frames]}
            common = dict(t_start_s=t_vals[0], t_end_s=t_vals[-1], ref=o["frame_refs"][0], basis=basis)
            if status == "observed_visual" and is_motion_tag(o["tag"]):
                # Quadros amostrados nunca são trecho contínuo: o mecanismo vira hipótese.
                status = "inference"
                if basis == "frame_sequence":
                    var = self._add(make_evidence(
                        self.video_key, status="observed_visual", source_type=source_type, tag="temporal_variation",
                        claim=f"variação visual observada entre {len(frames)} quadros amostrados: {o['text']}",
                        provenance=dict(prov, derived_from_tag=o["tag"]), **common))
                    ids.append(var["evidence_id"])
                    self.report["downgraded"].append(f"'{o['tag']}': {len(frames)} quadros mostram variação, não o mecanismo; "
                                                     "variação registrada como observed_visual e mecanismo como inference")
                else:
                    self.report["downgraded"].append(f"'{o['tag']}': movimento não se prova com {basis}; registrado como inference")
            ev = self._add(make_evidence(self.video_key, status=status, source_type=source_type, claim=o["text"],
                                         tag=o["tag"], provenance=prov, **common))
            ids.append(ev["evidence_id"])
        return ids

    def add_legacy_label(self, label: str, rule: str, source: str = "core.curation") -> str:
        """Saída de classificador legado (ex.: curation_category) entra como inferência, nunca como fato."""
        ev = self._add(make_evidence(self.video_key, status="inference", source_type="text_classifier",
                                     claim=f"rótulo legado '{label}' ({rule})", tag="legacy_label",
                                     provenance={"source": source, "rule": rule}))
        return ev["evidence_id"]

    def add_external_knowledge(self, claim: str, source: str) -> str:
        """Conhecimento prévio sobre ferramenta/produto (não visto no vídeo): sempre inferência, sem tempo."""
        ev = self._add(make_evidence(self.video_key, status="inference", source_type="external_knowledge", claim=claim,
                                     tag="external_knowledge", provenance={"source": source}))
        return ev["evidence_id"]

    def add_unverified(self, claim: str, source: str, t_start_s: Optional[float] = None,
                       t_end_s: Optional[float] = None) -> str:
        ev = self._add(make_evidence(self.video_key, status="unverified", source_type="derived", claim=claim,
                                     t_start_s=t_start_s, t_end_s=t_end_s, provenance={"source": source}))
        return ev["evidence_id"]

    # -- saída ------------------------------------------------------------
    def evidence(self) -> List[Dict[str, Any]]:
        return sorted(self._ev.values(), key=lambda e: (-1 if e["t_start_s"] is None else e["t_start_s"], e["evidence_id"]))

    def build(self) -> Dict[str, Any]:
        self.doc["evidence"] = self.evidence()
        self.doc["frames"].sort(key=lambda f: (f["t_s"], f["frame_id"]))
        self.doc["transcript"].sort(key=lambda s: (s["t_start_s"], s["segment_id"]))
        return self.doc
