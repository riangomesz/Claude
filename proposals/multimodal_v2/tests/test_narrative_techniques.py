import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.contract import validate_document
from ii_mm.narrative import coverage, suggest_blocks, validate_blocks
from ii_mm.normalize import Normalizer
from ii_mm.synthetic import sha
from ii_mm.techniques import build_techniques, level_for, open_questions

FR = {f"P0{i}": sha(f"f{i}") for i in range(1, 5)}


def norm(duration=40.0):
    n = Normalizer("ref_N", "instagram", "N", duration, content_sha256=sha("n"))
    n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": k, "t_s": 10 + i * 0.033, "sha256": v}
                                                    for i, (k, v) in enumerate(sorted(FR.items()))]}))
    return n


def say(n, segs):
    n.add_transcript(A.transcript_from_segments([{"start": a, "end": b, "text": t} for a, b, t in segs]))


def see(n, tag, refs, kind="observation"):
    n.add_observations(A.observations_from_json([{"frame_refs": refs, "t_s": 10, "tag": tag, "text": tag, "kind": kind}], "agent:t"))


class NarrativeTest(unittest.TestCase):
    def test_suggests_blocks_from_speech_visual_and_metadata(self):
        n = norm()
        say(n, [(0, 2, "para tudo e olha isso"), (2, 6, "nesse video vou mostrar o segredo"),
                (30, 34, "tem desconto e semana gratis"), (34, 38, "comenta e clica no link na bio")])
        see(n, "ui_screen_visible", ["P01"])
        n.add_metadata("link na bio")
        doc = n.build()
        blocks = suggest_blocks(doc)
        types = [b["type"] for b in blocks]
        for t in ("gancho", "contexto", "revelacao", "demonstracao", "oferta", "cta"):
            self.assertIn(t, types)
        self.assertTrue(all(b["status"] == "suggested" for b in blocks))
        self.assertIn("supported_visual", {b["support"] for b in blocks if b["type"] == "demonstracao"})
        self.assertIn("suggested_metadata", {b["support"] for b in blocks if b["type"] == "cta"})
        doc["narrative_blocks"] = blocks
        self.assertEqual(validate_document(doc), [])

    def test_cta_click_is_not_demonstration(self):
        n = norm(); say(n, [(10, 14, "comenta e clica no link na bio")])
        types = {b["type"] for b in suggest_blocks(n.build())}
        self.assertIn("cta", types)
        self.assertNotIn("demonstracao", types)
        n = norm(); say(n, [(10, 14, "agora clica em legendas automaticas")])
        self.assertIn("demonstracao", {b["type"] for b in suggest_blocks(n.build())})

    def test_position_only_hook_is_hypothesis(self):
        n = norm(); say(n, [(0.5, 2, "bom dia pessoal")])
        blocks = suggest_blocks(n.build())
        self.assertEqual([(b["type"], b["support"], b["rule"]) for b in blocks], [("gancho", "hypothesis", "posicao_inicial")])

    def test_no_hook_when_speech_starts_late(self):
        n = norm(); say(n, [(8, 10, "bom dia pessoal")])
        self.assertEqual(suggest_blocks(n.build()), [])

    def test_missing_overlapping_and_gaps(self):
        n = norm(); say(n, [(0, 5, "olha aqui o problema"), (20, 22, "link na bio")])
        doc = n.build()
        doc["narrative_blocks"] = suggest_blocks(doc)
        cov = coverage(doc)
        self.assertIn("beneficios", cov["missing_types"])
        self.assertIn((22.0, 40.0), cov["gaps"])
        self.assertTrue(cov["overlaps"])  # problema e demonstracao no mesmo segmento

    def test_rejected_blocks_do_not_count(self):
        n = norm(); say(n, [(0, 5, "link na bio")])
        doc = n.build()
        doc["narrative_blocks"] = suggest_blocks(doc)
        for b in doc["narrative_blocks"]:
            b["status"] = "rejected"
        self.assertIn("cta", coverage(doc)["missing_types"])

    def test_block_validation(self):
        n = norm(); doc = n.build()
        doc["narrative_blocks"] = [
            {"block_id": "b1", "type": "climax", "status": "suggested", "t_start_s": 0, "t_end_s": 1, "evidence_ids": []},
            {"block_id": "b2", "type": "cta", "status": "talvez", "t_start_s": 5, "t_end_s": None, "evidence_ids": ["ev_x"]},
            {"block_id": "b3", "type": "oferta", "status": "confirmed", "t_start_s": 5, "t_end_s": 99, "evidence_ids": []},
            {"block_id": "b3", "type": "oferta", "status": "pending", "t_start_s": None, "t_end_s": None, "evidence_ids": []}]
        probs = " | ".join(validate_blocks(doc))
        for frag in ("tipo inválido", "status inválido", "intervalo incompleto", "evidência inexistente", "intervalo inválido",
                     "confirmado sem evidência", "duplicado"):
            self.assertIn(frag, probs)


class TechniqueLevelsTest(unittest.TestCase):
    def test_five_levels_are_distinct(self):
        n = norm()
        see(n, "split_screen", ["P01"])                         # 1
        see(n, "punch_in_scale", ["P01", "P02"])                # 2
        see(n, "kinetic_typography", ["P01", "P02", "P03"])     # 3
        see(n, "mask_shape", ["P04"], kind="hypothesis")        # 4
        doc = n.build()
        techs = build_techniques(doc, suggestions=[{"technique": "split_screen", "text": "gravar tela e rosto separados e compor em 9:16",
                                                    "requires": ["captura de tela", "editor com camadas"], "author": "agent:t"}])
        got = {(t["technique"], t["level"]) for t in techs}
        self.assertEqual(got, {("split_screen", "observed_in_frame"), ("punch_in", "frame_pair_difference"),
                               ("tipografia_cinetica", "temporal_sequence"), ("mascara", "hypothesis"),
                               ("split_screen", "reproduction_suggestion")})
        doc["techniques"] = techs
        self.assertEqual(validate_document(doc), [])

    def test_frame_pair_never_proves_animation(self):
        n = norm(); see(n, "kinetic_typography", ["P01", "P02"])
        techs = build_techniques(n.build())
        self.assertEqual([(t["technique"], t["level"]) for t in techs], [("tipografia_cinetica", "hypothesis")])
        self.assertIn("confirmar", open_questions(techs)[0])

    def test_pair_tags_from_single_frame_are_hypotheses(self):
        n = norm(); see(n, "jump_cut_pair", ["P01"])
        self.assertEqual(build_techniques(n.build())[0]["level"], "hypothesis")

    def test_each_entry_states_what_it_proves(self):
        n = norm(); see(n, "punch_in_scale", ["P01", "P02"])
        t = build_techniques(n.build())[0]
        self.assertIn("não", "não " + t["does_not_prove"])
        self.assertIn("trajetória", t["does_not_prove"])

    def test_speech_and_measurements_create_no_technique(self):
        n = norm(); say(n, [(0, 3, "usei um jump cut e uma transição")])
        n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": 10, "score": 0.9}]}))
        self.assertEqual(build_techniques(n.build()), [])
        self.assertIsNone(level_for({"tag": "ui_screen_visible", "status": "observed_visual"}))

    def test_unknown_suggestion_technique(self):
        with self.assertRaises(ValueError):
            build_techniques(norm().build(), suggestions=[{"technique": "teletransporte", "text": "x"}])


if __name__ == "__main__":
    unittest.main()
