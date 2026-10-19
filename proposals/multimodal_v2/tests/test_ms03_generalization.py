"""Missão Suprema 03, Etapas 10 e 11: formatos diferentes do piloto e distinções de categorização (sintético).

Sem porcentagens de acerto: cada cenário verifica o comportamento esperado pelas regras do contrato.
"""
import re
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from tests.test_ms02_scenarios import Scenario, cats, tools
from ii_mm.technique_library import LEVEL_PROVES  # noqa: F401  (garante import do módulo)

ROOT = Path(__file__).resolve().parents[1]


def techs(doc):
    return {(t["technique"], t["level"]) for t in doc["techniques"]}


class GeneralizationTest(unittest.TestCase):
    def test_presenter_without_broll(self):
        d = Scenario("g01").say("hoje eu vou explicando como funciona o algoritmo").see("static_single_shot", "um único plano do apresentador").run()
        self.assertEqual(cats(d), {"conhecimento": "mentioned_speech", "edicao_audiovisual": "insufficient"})
        ed = next(c for c in d["categories"] if c["category"] == "edicao_audiovisual")
        self.assertEqual((ed["evidence_ids"], len(ed["contradicting_evidence_ids"])), ([], 1))  # só sinal CONTRA edição
        self.assertEqual(techs(d), set())

    def test_cinematic_edit_without_speech(self):
        d = Scenario("g02").see("cinematic_composition", "contraluz e profundidade rasa").see("cut_pair", "corte seco entre planos", refs=("P0", "P1")).run()
        self.assertEqual(cats(d), {"cinematografia": "supported_visual", "edicao_audiovisual": "supported_visual"})
        self.assertIn(("corte", "frame_pair_difference"), techs(d))
        self.assertEqual(d["transcript"], [])

    def test_screen_capture_only_tutorial(self):
        d = (Scenario("g03").see("ui_screen_visible", "tela do software sem apresentador")
             .see("step_sequence_visible", "menus sendo abertos em sequência", refs=("P0", "P1", "P2")).run())
        self.assertEqual(cats(d)["tutorial"], "supported_visual")
        self.assertEqual(cats(d)["demonstracao_ferramenta"], "supported_visual")
        self.assertEqual(tools(d), {})                # nome não legível → nenhuma ferramenta afirmada

    def test_fast_cut_reel_with_captions(self):
        d = (Scenario("g04").cuts(1.0, 1.6, 2.1, 2.9, 3.4)
             .see("burned_caption", "legenda grande centralizada").see("jump_cut_pair", "mesmo plano, salto de tempo", refs=("P1", "P2")).run())
        self.assertEqual(cats(d), {"edicao_audiovisual": "supported_visual"})
        c = next(c for c in d["categories"] if c["category"] == "edicao_audiovisual")
        self.assertEqual(len(c["context_evidence_ids"]), 5)   # cortes medidos ficam como contexto, não decidem
        self.assertIn(("jump_cut", "frame_pair_difference"), techs(d))

    def test_software_demo(self):
        d = Scenario("g05").say("olha so essa ferramenta, clica em gerar").see("tool_name_visible", "nome Notion legível").run()
        self.assertEqual(tools(d), {"Notion": "visually_identified"})
        self.assertEqual(cats(d)["demonstracao_ferramenta"], "supported_visual")

    def test_visual_portfolio(self):
        d = Scenario("g06").see("aesthetic_reference", "sequência de peças gráficas").see("typography_styled", "títulos em serifa", refs=("P1",)).meta("#moodboard").run()
        self.assertEqual(cats(d)["referencia_estetica"], "supported_visual")
        self.assertEqual(cats(d)["motion_design"], "supported_visual")   # tipografia estilizada estática; animação não afirmada
        self.assertIn(("tipografia", "observed_in_frame"), techs(d))
        self.assertNotIn(("tipografia_cinetica", "temporal_sequence"), techs(d))

    def test_physical_product_commercial(self):
        d = Scenario("g07").say("compre agora com cupom").see("sales_offer_on_screen", "preço e botão de compra", refs=("P2",)).see("cinematic_look", "produto com luz de estúdio", refs=("P1",)).run()
        self.assertEqual(cats(d)["marketing_vendas"], "supported_visual")
        self.assertEqual(cats(d)["cinematografia"], "supported_visual")
        self.assertEqual(tools(d), {})

    def test_abstract_motion_graphics(self):
        d = Scenario("g08").see("motion_transition_in_clip", "formas se transformam", refs=("P0", "P1", "P2")).run()
        self.assertEqual(cats(d), {"motion_design": "hypothesis"})           # 3 quadros: variação vista, mecanismo hipótese
        self.assertIn(("observed_visual", "temporal_variation"), {(e["status"], e["tag"]) for e in d["evidence"]})

    def test_educational_content(self):
        d = Scenario("g09").say("você sabia que a luz muda a cor percebida", "entenda o motivo").see("informational_on_screen", "diagrama explicativo").run()
        self.assertEqual(cats(d), {"conhecimento": "supported_visual"})

    def test_aesthetic_reference_without_explanation(self):
        d = Scenario("g10").see("aesthetic_reference", "paleta em tons pastéis").run()
        self.assertEqual(cats(d), {"referencia_estetica": "supported_visual"})
        self.assertEqual(d["narrative_blocks"], [])

    def test_video_without_metadata(self):
        d = Scenario("g11").run()
        self.assertEqual((d["categories"], d["tools"], d["techniques"]), ([], [], []))
        self.assertIsNone(d["reference"].get("author_handle"))

    def test_contradictory_evidence(self):
        d = Scenario("g12").say("vou mostrar a oferta").see("no_offer_on_screen", "nenhum preço na tela", refs=("P3",)).see("sales_offer_on_screen", "selo de desconto", refs=("P1",)).run()
        m = next(c for c in d["categories"] if c["category"] == "marketing_vendas")
        self.assertEqual(m["support"], "supported_visual")
        self.assertTrue(m["contested"])
        self.assertEqual(len(m["contradicting_evidence_ids"]), 1)

    def test_core_has_no_pilot_specific_constants(self):
        for p in (ROOT / "ii_mm").rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"DQV5dm6gCvH|dqv5dm6gcvh|0\.448|57\.16", text), p.name)


class CategorizationDistinctionsTest(unittest.TestCase):
    """Um só vídeo sintético com todos os tipos de afirmação: cada um precisa cair no lugar certo."""

    @classmethod
    def setUpClass(cls):
        s = (Scenario("dist")
             .say("explicando o conceito de automação", "eu uso o n8n para isso", "fica 100% automatico e com desconto")
             .see("tool_name_visible", "nome CapCut legível")
             .see("split_screen", "tela dividida", refs=("P1",))
             .see("kinetic_typography", "texto muda entre quadros", refs=("P0", "P1"))
             .see("step_sequence_visible", "passos na interface", refs=("P0", "P1", "P2"))
             .see("aesthetic_reference", "paleta neon", refs=("P3",)))
        s.n.add_unverified("'100% automático' (promessa da fala, sem demonstração)", source="curadoria", t_start_s=8, t_end_s=11)
        s.n.doc["reference"]["subject"] = "automação de edição"
        cls.d = s.run()

    def test_subject_is_metadata_not_category(self):
        self.assertEqual(self.d["reference"]["subject"], "automação de edição")

    def test_tool_mentioned_vs_visually_identified(self):
        self.assertEqual(tools(self.d), {"CapCut": "visually_identified", "n8n": "mentioned_only"})

    def test_observed_vs_inferred_technique(self):
        t = techs(self.d)
        self.assertIn(("split_screen", "observed_in_frame"), t)
        self.assertIn(("tipografia_cinetica", "hypothesis"), t)

    def test_demonstrated_process(self):
        self.assertEqual(cats(self.d)["tutorial"], "supported_visual")

    def test_commercial_promise_is_unverified(self):
        ev = [e for e in self.d["evidence"] if "100%" in e["claim"]]
        self.assertEqual({e["status"] for e in ev}, {"transcript_claim", "unverified"})
        self.assertEqual(cats(self.d)["marketing_vendas"], "mentioned_speech")    # dito, não visto

    def test_transferable_knowledge_and_aesthetic_reference(self):
        self.assertEqual(cats(self.d)["conhecimento"], "mentioned_speech")
        self.assertEqual(cats(self.d)["referencia_estetica"], "supported_visual")


if __name__ == "__main__":
    unittest.main()
