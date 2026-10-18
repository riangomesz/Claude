"""Adaptadores do legado com fixtures que seguem os formatos reais do Projeto-MVP (valores sintéticos)."""
import json
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.classifier import Classifier
from ii_mm.contract import validate_document
from ii_mm.legacy import (from_instagram_item, from_intelligence_card, from_transition_candidates, from_vision_macro,
                          to_legacy_fields)
from ii_mm.normalize import Normalizer
from ii_mm.synthetic import sha

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "legacy"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


class InstagramItemAdapterTest(unittest.TestCase):
    def test_full_row_maps_preserves_and_reports(self):
        n, rep = from_instagram_item(load("instagram_item_row"))  # duração e hash vêm das colunas media_*
        doc = Classifier().classify(n.build())
        self.assertEqual(validate_document(doc), [])
        self.assertEqual(doc["reference"]["legacy_item_id"], "SYNTHleg01")
        self.assertEqual(doc["video"]["video_id"], "SYNTHleg01")
        self.assertEqual(len(doc["transcript"]), 2)
        self.assertEqual(rep.unmapped, ["coluna_futura_desconhecida"])
        self.assertIn("triage_decision", rep.preserved)
        self.assertEqual(doc["video"]["content_sha256"], load("instagram_item_row")["media_sha256"].lower())  # media_sha256 vira identidade de conteúdo
        self.assertEqual((doc["video"]["width"], doc["video"]["height"]), (1080, 1920))
        statuses = {e["status"] for e in doc["evidence"]}
        self.assertEqual(statuses, {"metadata_claim", "transcript_claim", "inference"})

    def test_does_not_reclassify_human_decisions(self):
        n, rep = from_instagram_item(load("instagram_item_row"), duration_s=30.0)
        fields = {d["field"] for d in rep.human_decisions}
        self.assertEqual(fields, {"editorial_category", "triage_decision"})
        doc = n.build()
        legacy_labels = [e["claim"] for e in doc["evidence"] if e.get("tag") == "legacy_label"]
        self.assertEqual(len(legacy_labels), 1)  # só curation_category (automático); a editorial manual não vira evidência
        self.assertIn("relevante", legacy_labels[0])

    def test_reversible_fields(self):
        row = load("instagram_item_row")
        n, _ = from_instagram_item(row, duration_s=30.0)
        back = to_legacy_fields(n.build())
        for k in ("id", "canonical_shortcode", "url", "owner_username", "triage_decision", "quality_rating", "curator_note", "media_status"):
            self.assertEqual(back[k], row[k], k)

    def test_partial_inputs(self):
        n, rep = from_instagram_item({"id": "SYNTHmin01"}, duration_s=10)
        self.assertEqual(validate_document(n.build()), [])
        self.assertEqual(rep.unmapped, [])
        n, rep = from_instagram_item({"id": "SYNTHmin02"})
        self.assertIsNone(n)
        self.assertIn("duração", rep.blocking)
        n, rep = from_instagram_item({})
        self.assertIn("sem id", rep.blocking)

    def test_untimed_transcript_and_bad_json(self):
        row = {"id": "SYNTHut01", "audio_transcript": "fala sem tempos", "hashtags_json": "{quebrado", "origin_platform": "facebook"}
        n, rep = from_instagram_item(row, duration_s=12)
        doc = n.build()
        tc = [e for e in doc["evidence"] if e["status"] == "transcript_claim"][0]
        self.assertTrue(tc["provenance"]["untimed"])
        self.assertEqual((tc["t_start_s"], tc["t_end_s"]), (0.0, 12.0))
        self.assertEqual(doc["reference"]["platform"], "other")
        self.assertTrue(any("ilegível" in w for w in rep.warnings))
        self.assertEqual(validate_document(doc), [])

    def test_instagram_item_model_dump_shape(self):
        model = {"id": "SYNTHmd01", "url": None, "post_type": "reel", "hashtags": ["#a"], "caption": "legenda"}
        n, rep = from_instagram_item(model, duration_s=5)
        self.assertIn("hashtags_json", rep.mapped)


class VisionAndTemporalAdapterTest(unittest.TestCase):
    def norm(self):
        return Normalizer("ref_V", "instagram", "SYNTHleg01", 30.0, content_sha256=sha("leg"))

    def test_simulation_never_becomes_evidence(self):
        n = self.norm()
        rep = from_vision_macro(n, load("vision_macro_simulacao"), "macro_1")
        self.assertIn("simulação", rep.blocking)
        self.assertEqual(n.build()["evidence"], [])

    def test_model_observations_are_unverified_not_visual(self):
        n = self.norm()
        rep = from_vision_macro(n, load("vision_macro_observado"), "macro_1")
        doc = n.build()
        self.assertEqual(sorted({e["status"] for e in doc["evidence"]}), ["inference", "unverified"])
        self.assertIn("art_direction", rep.preserved)
        self.assertEqual(validate_document(doc), [])
        self.assertTrue(doc["pending"])

    def test_transition_candidates_are_measurement_plus_hypothesis(self):
        n = self.norm()
        rep = from_transition_candidates(n, load("transition_candidates"))
        doc = n.build()
        self.assertEqual(sorted(e["status"] for e in doc["evidence"]), ["inference", "measured_signal"])
        self.assertTrue(any("timestamp" in w for w in rep.warnings))
        self.assertEqual(Classifier().classify(doc)["categories"], [])  # medição e hipótese de limiar não classificam sozinhas


class IntelligenceCardAdapterTest(unittest.TestCase):
    def test_card_v2_preserves_separation(self):
        n = Normalizer("ref_C", "instagram", "SYNTHleg01", 30.0, content_sha256=sha("leg"))
        rep = from_intelligence_card(n, load("intelligence_card_v2"))
        doc = Classifier().classify(n.build())
        self.assertEqual(validate_document(doc), [])
        by = {}
        for e in doc["evidence"]:
            by.setdefault(e["status"], []).append(e)
        self.assertEqual(len(by["transcript_claim"]), 1)
        self.assertEqual({e["ref"] for e in by["observed_visual"]}, {"F07", "F08"})
        self.assertTrue(all(e["basis"] == "static_frame" for e in by["observed_visual"]))
        self.assertTrue(any("100% automático" in e["claim"] for e in by["unverified"]))
        self.assertIn("tipo de observação sem tag: gesto_do_apresentador", rep.unmapped)
        self.assertNotIn("temporal_sequence", {t.get("level") for t in doc["techniques"]})
        self.assertEqual(len([p for p in doc["pending"] if p["pending_id"].startswith("ficha:")]), 1)

    def test_unknown_schema_blocked(self):
        n = Normalizer("ref_C", "instagram", "V", 30.0)
        self.assertIsNotNone(from_intelligence_card(n, {"schema_version": "outra"}).blocking)

    def test_confirmed_motion_requires_clip(self):
        card = load("intelligence_card_v2")
        card["separacao_de_evidencias"]["movimento_confirmado"]["itens"] = [{"descricao": "zoom"}]
        n = Normalizer("ref_C", "instagram", "V", 30.0)
        rep = from_intelligence_card(n, card)
        self.assertTrue(any("video_clip" in u for u in rep.unmapped))


if __name__ == "__main__":
    unittest.main()


import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402


@unittest.skipUnless(os.environ.get("PROJETO_MVP_DIR"), "defina PROJETO_MVP_DIR para conferir contra o DDL real")
class RealSchemaCompatibilityTest(unittest.TestCase):
    def test_fixture_columns_exist_in_real_schema_and_roundtrip_through_sqlite(self):
        from ii_mm.db.legacy_fixture import build_legacy_catalog
        from ii_mm.legacy import INSTAGRAM_ITEM_MAPPING, LEGACY_PRESERVED
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "legacy_compat.sqlite"
            build_legacy_catalog(db, Path(os.environ["PROJETO_MVP_DIR"]))
            conn = sqlite3.connect(str(db))
            try:
                conn.row_factory = sqlite3.Row
                real = {r["name"] for r in conn.execute("PRAGMA table_info(instagram_items)")}
                expected = set(INSTAGRAM_ITEM_MAPPING) | set(LEGACY_PRESERVED)
                self.assertEqual(sorted(expected - real), [], "colunas mapeadas que não existem no DDL real")
                row = {k: v for k, v in load("instagram_item_row").items() if k in real}
                conn.execute(f"INSERT INTO instagram_items ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
                stored = dict(conn.execute("SELECT * FROM instagram_items WHERE id = ?", ("SYNTHleg01",)).fetchone())
            finally:
                conn.close()
        n, rep = from_instagram_item(stored, duration_s=30.0)
        self.assertEqual(validate_document(Classifier().classify(n.build())), [])
        self.assertEqual(rep.unmapped, [], f"colunas reais sem destino: {rep.unmapped}")
