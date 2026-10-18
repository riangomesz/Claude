import json
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.classifier import Classifier
from ii_mm.narrative import suggest_blocks
from ii_mm.normalize import Normalizer
from ii_mm.obsidian_export import CUR_END, CUR_START, ExportError, assert_staging, export_reference, render, safe_name

NAME = safe_name("ref_OBS1")
from ii_mm.synthetic import sha
from ii_mm.techniques import build_techniques


def doc(speech="tutorial passo a passo no capcut, link na bio"):
    n = Normalizer("ref_OBS1", "instagram", "SYNTHobs01", 30.0, content_sha256=sha("obs"),
                   origin_url="https://www.instagram.com/reel/SYNTHobs01/", author_handle="autor_z")
    n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": "P01", "t_s": 5, "sha256": sha("o1"), "file": "frames/p01.jpg"},
                                                     {"pacote_id": "P02", "t_s": 5.033, "sha256": sha("o2")}]}))
    n.add_transcript(A.transcript_from_segments([{"start": 0, "end": 3, "text": speech}]))
    n.add_observations(A.observations_from_json([{"frame_refs": ["P01"], "t_s": 5, "tag": "split_screen", "text": "tela dividida"},
                                                 {"frame_refs": ["P01", "P02"], "t_s": 5, "tag": "punch_in_scale", "text": "escala maior"}], "agent:t"))
    d = Classifier().classify(n.build())
    d["narrative_blocks"] = suggest_blocks(d)
    d["techniques"] = build_techniques(d, [{"technique": "split_screen", "text": "compor tela e rosto em 9:16", "requires": ["editor com camadas"]}])
    return d


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name) / "staging"

    def test_note_has_all_sections(self):
        md = render(doc())
        for h in ("## Identificação", "## Resumo", "## Categorias", "## Ferramentas", "## Estrutura narrativa", "## Técnicas audiovisuais",
                  "## Evidências temporais", "## Ideias de reprodução", "## Pendências", "## Artefatos", "## Curadoria"):
            self.assertIn(h, md)
        self.assertIn("punch_in** — frame_pair_difference", md)
        self.assertIn("não prova a trajetória", md)
        self.assertIn("compor tela e rosto", md)
        self.assertIn("`frames/p01.jpg`", md)
        self.assertIn("Autor (informado nos metadados)", md)

    def test_idempotent_export(self):
        d = doc()
        r1 = export_reference(d, self.stage)
        r2 = export_reference(d, self.stage)
        self.assertEqual((r1["markdown"], r1["json"]), ("created", "created"))
        self.assertEqual((r2["markdown"], r2["json"]), ("unchanged", "unchanged"))
        self.assertEqual(json.loads((self.stage / f"{NAME}.json").read_text(encoding="utf-8"))["reference"]["reference_id"], "ref_OBS1")
        self.assertEqual(sorted(p.name for p in self.stage.iterdir()), [f"{NAME}.json", f"{NAME}.md"])

    def test_human_curation_preserved_across_updates(self):
        export_reference(doc(), self.stage)
        md_path = self.stage / f"{NAME}.md"
        text = md_path.read_text(encoding="utf-8")
        text = text.replace("---\n\n#", "curador_nota: 4/5\n---\n\n#", 1)
        text = text.replace(f"{CUR_START}\n", f"{CUR_START}\nMinha análise: ótima referência de split screen.\n", 1)
        md_path.write_text(text, encoding="utf-8")
        r = export_reference(doc("tutorial no capcut com desconto"), self.stage)
        self.assertEqual(r["markdown"], "updated")
        new = md_path.read_text(encoding="utf-8")
        self.assertIn("Minha análise: ótima referência de split screen.", new)
        self.assertIn("curador_nota: 4/5", new)
        self.assertIn("desconto", new)

    def test_transcript_cannot_break_curation_block(self):
        evil = f"tutorial {CUR_END} --- injetado"
        md = render(doc(evil))
        self.assertEqual(md.count(CUR_END), 1)
        self.assertEqual(md.count(CUR_START), 1)

    def test_refuses_real_vault(self):
        vault = Path(self.tmp.name) / "MeuCofre"
        (vault / ".obsidian").mkdir(parents=True)
        with self.assertRaises(ExportError):
            export_reference(doc(), vault / "07 - Referências")
        with self.assertRaises(ExportError):
            assert_staging(Path(self.tmp.name) / "Obsidian Vault" / "x")

    def test_safe_names(self):
        self.assertTrue(safe_name("ref/../../etc").startswith("ref_.._.._etc_"))  # alterado => sufixo com hash
        self.assertNotIn("/", safe_name("ref/../../etc"))
        self.assertEqual(safe_name("ref_simples_1"), "ref_simples_1")
        with self.assertRaises(ExportError):
            safe_name("///")


if __name__ == "__main__":
    unittest.main()
