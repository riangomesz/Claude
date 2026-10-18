"""Gerador determinístico de referências sintéticas (para testes e benchmarks).

Nada aqui representa um vídeo real: IDs começam com SYNTH, hashes são derivados da semente.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List

from .contract import empty_document, make_evidence
from .evidence_rules import category_support

TOOLS = ("ToolAlpha", "ToolBeta", "ToolGamma", "ToolDelta", "ToolEpsilon")
SUBJECTS = ("prompting", "edicao", "automacao", "motion", "vendas", "fotografia", "agentes")
SPEECH = {
    "tutorial": "primeiro abra o painel e em seguida clique em gerar, passo a passo",
    "marketing_vendas": "link na bio com desconto para os primeiros clientes",
    "automacao": "esse workflow no n8n automatiza tudo com um webhook",
    "conhecimento": "voce sabia que da para entender isso em um minuto",
    "demonstracao_ferramenta": "olha so essa ferramenta nova",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def synthetic_url(platform: str, i: int) -> str:
    """URLs com formato de plataforma e IDs inequivocamente sintéticos (prefixo SYNTH / 9999...)."""
    if platform == "youtube":
        return f"https://youtu.be/SYNTH{i:06d}"
    if platform == "tiktok":
        return f"https://www.tiktok.com/@synth/video/9999{i:010d}"
    return f"https://www.instagram.com/reel/SYNTH{i:06d}/"


def make_reference(i: int, seed: int = 7) -> Dict[str, Any]:
    rnd = random.Random(seed * 1_000_003 + i)
    vid = f"SYNTH{i:06d}"
    dur = round(rnd.uniform(8.0, 90.0), 3)
    content = sha(f"content:{seed}:{i}")
    platform = rnd.choice(("instagram", "instagram", "youtube", "tiktok"))
    doc = empty_document(
        reference_id=f"ref_{vid}", platform=platform, video_id=vid, duration_s=dur, content_sha256=content,
        origin_url=synthetic_url(platform, i), author_handle=f"autor_{rnd.randrange(40):02d}",
    )
    doc["reference"]["subject"] = rnd.choice(SUBJECTS)
    cats = rnd.sample(list(SPEECH), k=rnd.randint(1, 3))
    t = 0.0
    for n, cat in enumerate(cats, start=1):
        end = min(dur, t + rnd.uniform(2.0, 6.0))
        doc["transcript"].append({"segment_id": f"s{n}", "t_start_s": round(t, 3), "t_end_s": round(end, 3),
                                  "text": SPEECH[cat], "source": "whisper"})
        t = end
    frame_t = round(min(dur, rnd.uniform(0.5, dur)), 3)
    doc["frames"].append({"frame_id": "F01", "t_s": frame_t, "sha256": sha(f"frame:{seed}:{i}"),
                          "width": 1080, "height": 1920})
    evs: Dict[str, List[Dict[str, Any]]] = {}
    for seg, cat in zip(doc["transcript"], cats):
        e = make_evidence(content, status="transcript_claim", source_type="whisper", claim=seg["text"],
                          t_start_s=seg["t_start_s"], t_end_s=seg["t_end_s"], ref=seg["segment_id"],
                          provenance={"source": "synthetic", "extractor": "whisper-synth"})
        doc["evidence"].append(e)
        evs.setdefault(cat, []).append(e)
    tool = rnd.choice(TOOLS)
    if rnd.random() < 0.5:
        e = make_evidence(content, status="observed_visual", source_type="agent_observation",
                          claim=f"tela da {tool} visível", t_start_s=frame_t, ref="F01", tag="ui_screen_visible",
                          basis="static_frame", provenance={"source": "synthetic", "artifact_sha256": doc["frames"][0]["sha256"]})
        doc["evidence"].append(e)
        evs.setdefault("demonstracao_ferramenta", []).append(e)
        doc["tools"].append({"name": tool, "status": "visually_identified", "visual_evidence_ids": [e["evidence_id"]],
                             "mention_evidence_ids": []})
        doc["techniques"].append({"technique": "split_screen", "level": "observed_in_frame",
                                  "evidence_ids": [e["evidence_id"]]})
    else:
        doc["tools"].append({"name": tool, "status": "unverified", "visual_evidence_ids": [], "mention_evidence_ids": []})
    for cat, items in sorted(evs.items()):
        doc["categories"].append({"category": cat, "support": category_support(items),
                                  "evidence_ids": [x["evidence_id"] for x in items],
                                  "contradicting_evidence_ids": [], "review_state": "pending"})
    return doc
