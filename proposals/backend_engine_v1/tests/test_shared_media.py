"""Mesmo arquivo em duas referências: identidade de conteúdo e a incompatibilidade I1 do ii_mm (análise corrente por vídeo)."""
import unittest

from tests._util import TempEngine
from ii_be import knowledge as K
from ii_be.classification import ClassificationService
from ii_be.curation import CurationService
from ii_be.refscope import RefScopedRepository
from ii_be.synthetic import seed_media_reference
from ii_mm.db.repository import Repository


class SharedMediaTest(unittest.TestCase):
    def setUp(self):
        self.t = TempEngine().__enter__()
        e = self.t.engine
        self.ig = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHshare1/", "mesmo",
                                       metadata={"caption": "Tutorial CapCut legendas passo a passo"})["ingest"].reference_id
        self.yt = seed_media_reference(e, "https://www.youtube.com/watch?v=SYNTHshare2", "mesmo",
                                       metadata={"title": "Promo: cupom de desconto, link na bio"})["ingest"].reference_id
        e.run()

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_content_identity_reaches_ii_mm(self):
        """Regressão D-BE1: `assemble` não dependia de `acquire` e o documento ia ao ii_mm sem o SHA-256 da mídia."""
        c = self.t.engine.conn
        self.assertEqual(c.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 1)
        self.assertIsNotNone(c.execute("SELECT content_sha256 FROM videos").fetchone()[0])
        self.assertEqual(sorted(r[0] for r in c.execute("SELECT reference_id FROM ref_videos")), sorted([self.ig, self.yt]))

    def test_ii_mm_current_analysis_is_per_video_and_backend_scopes_it_per_reference(self):
        c = self.t.engine.conn
        plain = Repository(c)
        doc_for_ig = plain.get_document(plain.current_analysis_id(self.ig))
        self.assertEqual(doc_for_ig["reference"]["reference_id"], self.yt)      # comportamento do ii_mm (I1)
        scoped = RefScopedRepository(c)
        self.assertEqual(scoped.get_document(scoped.current_analysis_id(self.ig))["reference"]["reference_id"], self.ig)
        self.assertEqual(scoped.get_document(scoped.current_analysis_id(self.yt))["reference"]["reference_id"], self.yt)

    def test_knowledge_curation_and_facets_follow_the_right_reference(self):
        e = self.t.engine
        kn = {r["reference_id"]: {(x["facet"], x["value"]) for x in K.knowledge_for(e.conn, r["reference_id"])}
              for r in [{"reference_id": self.ig}, {"reference_id": self.yt}]}
        self.assertIn(("categoria", "tutorial"), kn[self.ig])
        self.assertIn(("promessa_comercial", "oferta_ou_chamada_comercial"), kn[self.yt])
        cur = CurationService(e.conn, self.t.clock)
        cur.decide(self.ig, "accept_category", "human:ana", category="tutorial")
        facets = ClassificationService(e).result(self.ig)["facets"]
        tut = [x for x in facets["categoria_editorial"] if x["category"] == "tutorial"][0]
        self.assertEqual(tut["review_state"], "accepted")
        self.assertNotIn("tutorial", [x["category"] for x in ClassificationService(e).result(self.yt)["facets"]["categoria_editorial"]
                                      if x["review_state"] == "accepted"])


if __name__ == "__main__":
    unittest.main()
