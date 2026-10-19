"""Gera os exemplos de contrato em `contratos/` a partir do próprio código (nunca escritos à mão).

Uso: python -X utf8 tools/contracts.py [--check]
Com --check, só confere se os arquivos publicados são iguais aos gerados (usado por tests/test_contracts.py).
Todos os valores são sintéticos e determinísticos (relógio manual, banco em memória).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from ii_be.api import ServiceAPI  # noqa: E402
from ii_be.clock import FakeClock  # noqa: E402
from ii_be.engine import Engine  # noqa: E402
from ii_be.gateway import REQUEST_SCHEMA, AnalysisGateway, MockProvider  # noqa: E402
from ii_be.ingest import record_from_url, records_from_meta_export  # noqa: E402

OUT = HERE / "contratos"


def examples() -> dict:
    ex = {}
    rec = record_from_url("https://www.instagram.com/reel/SYNTHcontrato1/", metadata={
        "caption": "Legendas automáticas no CapCut", "hashtags": ["#capcut"], "author_handle": "autor_sintetico", "duration_s": 24.0},
        observed_at="2026-10-19T00:00:00+00:00")
    ex["ii.be.ingest.v1.exemplo.json"] = rec
    meta, _ = records_from_meta_export({"saved_saved_media": [{"title": "autor_sintetico", "string_map_data": {
        "Saved on": {"href": "https://www.instagram.com/p/SYNTHcontrato2/", "timestamp": 1760000000}}}]}, "saved_posts.json")
    ex["ii.be.ingest.v1.meta_export.exemplo.json"] = meta[0]
    with tempfile.TemporaryDirectory() as t:
        e = Engine(":memory:", root=Path(t) / "store", clock=FakeClock())
        try:
            api = ServiceAPI.from_engine(e)
            req = {"record": rec, "idempotency_key": "exemplo-ingest-0001"}
            ex["ii.be.api.v1.ingest_reference.request.json"] = req
            resp = api.handle("ingest_reference", req)
            ex["ii.be.api.v1.ingest_reference.response.json"] = resp
            ref = resp["data"]["reference_id"]
            ex["ii.be.api.v1.register_artifact.request.json"] = {"reference_id": ref, "kind": "srt", "relpath": "tools/SYNTHcontrato1/legenda.srt",
                                                                 "origin": "tool:whisper", "idempotency_key": "exemplo-artefato-0001"}
            ex["ii.be.api.v1.register_curation.request.json"] = {"reference_id": ref, "action": "triage", "reviewer": "human:curador",
                                                                 "params": {"value": "manter"}, "expected_etag": "0.0",
                                                                 "idempotency_key": "exemplo-curadoria-0001"}
            ex["ii.be.api.v1.search.request.json"] = {"filters": {"category": "tutorial", "tool": "CapCut", "requires": ["visual"],
                                                                  "text": "legendas"}, "limit": 20}
            ex["ii.be.api.v1.erro.exemplo.json"] = api.handle("get_reference", {"reference_id": "../../etc/passwd"})
            ev = e.conn.execute("SELECT event_id, type, aggregate_id, payload_json FROM be_outbox ORDER BY event_seq LIMIT 1").fetchone()
            ex["ii.be.event.v1.exemplo.json"] = {"event_id": ev["event_id"], "type": ev["type"], "aggregate_id": ev["aggregate_id"],
                                                 "payload": json.loads(ev["payload_json"]), "schema": "ii.be.event.v1"}
            gw = AnalysisGateway(e.conn, e.clock, {"mock": MockProvider()})
            areq = {"schema_version": REQUEST_SCHEMA, "provider": "mock", "model": "mock-visual-1", "prompt_version": "visual_review.v1",
                    "reference_id": ref, "budget": {"max_usd": 0},
                    "evidence": {"reference_id": ref, "frames": [{"frame_id": "P01", "t_s": 9.0}],
                                 "text_evidence": [{"evidence_id": "ev_exemplo", "status": "transcript_claim", "claim": "passo a passo no CapCut",
                                                    "untrusted": True}]}}
            ex["ii.be.analysis_request.v1.exemplo.json"] = areq
            done = gw.execute(gw.submit(areq)["request_id"])
            ex["ii.be.analysis_result.v1.exemplo.json"] = done["result"]
        finally:
            e.close()
    return ex


def render(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    stale = []
    for name, obj in examples().items():
        path = OUT / name
        text = render(obj)
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            OUT.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print("desatualizados:", ", ".join(stale))
        return 1
    print("contratos ok" if check else "contratos gerados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
