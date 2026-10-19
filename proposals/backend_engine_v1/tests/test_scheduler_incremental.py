"""Tarefas 06, 08 e 09: grafo de dependências, etapas audiovisuais e processamento incremental."""
import collections
import unittest

from tests._util import TempEngine
from ii_be import incremental as I
from ii_be.ingest import record_from_url
from ii_mm.db.repository import Repository
from ii_mm.review import ReviewService
from ii_be.scheduler import MEDIA_GRAPH, CycleError, StageGraph
from ii_be.synthetic import seed_media_reference, tool_outputs

URL = "https://www.instagram.com/reel/SYNTHsch01/"
META = {"caption": "Legendas automáticas no CapCut", "hashtags": ["#capcut", "#tutorial"], "author_handle": "autor_demo"}


def outcomes(done):
    return collections.Counter((d["stage"], d["outcome"]) for d in done if d["stage"])


def stage_attempt_outcomes(e, ref, stage):
    return [r[0] for r in e.conn.execute(
        "SELECT a.outcome FROM be_job_attempts a JOIN be_jobs j ON j.job_id = a.job_id WHERE j.reference_id = ? AND j.stage = ? "
        "ORDER BY a.attempt_id", (ref, stage))]


class GraphTest(unittest.TestCase):
    def test_cycle_and_unknown_dependency_are_rejected(self):
        with self.assertRaises(CycleError):
            StageGraph({"a": ("b",), "b": ("c",), "c": ("a",)})
        with self.assertRaises(ValueError):
            StageGraph({"a": ("fantasma",)})
        self.assertEqual(MEDIA_GRAPH.order[0], "acquire")
        self.assertEqual(MEDIA_GRAPH.order[-1], "export")
        self.assertEqual(MEDIA_GRAPH.descendants({"transcribe"}), ["transcribe", "assemble", "classify", "index", "export"])

    def test_independent_stages_are_ready_in_parallel(self):
        with TempEngine() as t:
            e = t.engine
            s = seed_media_reference(e, URL, "sch01", metadata=META)
            plan = e.plan(s["ingest"].reference_id)
            self.assertEqual(len(plan.enqueued), len(MEDIA_GRAPH.order))
            w = e.worker(owner="w0")
            w.run_once()                                          # acquire
            ready = [e.queue.claim(f"w{i}") for i in range(1, 6)]
            stages = sorted(j.stage for j in ready if j)
            self.assertEqual(stages, ["audio", "probe", "scenes"])  # só o que não depende de mais nada


class IncrementalTest(unittest.TestCase):
    def full(self, t, seed="sch01", url=URL):
        s = seed_media_reference(t.engine, url, seed, metadata=META)
        done = t.engine.run()
        return s, done

    def test_replan_reuses_everything_and_does_not_duplicate(self):
        with TempEngine() as t:
            e = t.engine
            s, done = self.full(t)
            ref = s["ingest"].reference_id
            self.assertTrue(all(o == "completed" for (_, o) in outcomes(done)))
            again = e.plan(ref)
            self.assertEqual(again.enqueued, {})
            self.assertEqual(sorted(again.reused), sorted(MEDIA_GRAPH.order))
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 1)

    def test_replanning_while_active_does_not_duplicate(self):
        with TempEngine() as t:
            e = t.engine
            s = seed_media_reference(e, URL, "dup01", metadata=META)
            ref = s["ingest"].reference_id
            p1 = e.plan(ref)
            p2 = e.plan(ref)
            self.assertEqual(p2.enqueued, {})
            self.assertEqual(sorted(p2.already_active), sorted(p1.enqueued))
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_jobs WHERE kind='stage'").fetchone()[0], len(MEDIA_GRAPH.order))

    def test_new_transcript_reprocesses_only_dependents_and_keeps_history(self):
        with TempEngine() as t:
            e = t.engine
            s, _ = self.full(t)
            ref = s["ingest"].reference_id
            first_aid = I.current_result(e.conn, ref, "classify")["result"]["analysis_id"]
            srt = tool_outputs()["srt"].decode() + "\n6\n00:00:20,000 --> 00:00:23,000\nAgora automatize tudo com n8n e webhook\n"
            e.store.write_bytes("tools/sch01/srt_v2.srt", srt.encode())
            e.register_artifact(ref, "srt", "tools/sch01/srt_v2.srt", origin="tool:whisper")
            done = e.run()
            executed = {d["stage"] for d in done if d["stage"] and d["outcome"] == "completed"}
            self.assertEqual(executed, {"transcribe", "assemble", "classify", "index", "export"})
            for st in ("acquire", "probe", "scenes", "frames"):
                self.assertEqual(stage_attempt_outcomes(e, ref, st), ["completed"], st)   # nunca refeitas
            new_aid = I.current_result(e.conn, ref, "classify")["result"]["analysis_id"]
            self.assertNotEqual(new_aid, first_aid)
            hist = {r[0]: r[1] for r in e.conn.execute("SELECT analysis_id, status FROM analyses")}
            self.assertEqual(hist, {first_aid: "superseded", new_aid: "current"})
            self.assertIn("automacao", I.current_result(e.conn, ref, "classify")["result"]["categories"])

    def test_taxonomy_change_reruns_classify_with_early_cutoff(self):
        with TempEngine() as t:
            e = t.engine
            s, _ = self.full(t)
            ref = s["ingest"].reference_id
            e.cfg.taxonomy_version = "tax-nova-sintetica"
            plan = e.plan(ref)
            self.assertEqual(sorted(plan.enqueued), ["classify", "export", "index"])
            e.run()
            self.assertEqual(stage_attempt_outcomes(e, ref, "classify"), ["completed", "completed"])
            self.assertEqual(stage_attempt_outcomes(e, ref, "index"), ["completed", "reused"])    # classificação igual
            self.assertEqual(stage_attempt_outcomes(e, ref, "transcribe"), ["completed"])
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 1)   # ii_mm: mesma entrada

    def test_human_curation_reindexes_without_touching_classification(self):
        with TempEngine() as t:
            e = t.engine
            s, _ = self.full(t)
            ref = s["ingest"].reference_id
            rv = ReviewService(Repository(e.conn))
            rv.reject_category(ref, "marketing_vendas", "human:ana", "oferta é do criador, não tema do vídeo")
            done = e.run()
            executed = sorted(d["stage"] for d in done if d["stage"] and d["outcome"] == "completed")
            self.assertEqual(executed, ["export", "index"])
            self.assertEqual(stage_attempt_outcomes(e, ref, "classify"), ["completed"])
            row = e.conn.execute("SELECT status, authority FROM be_knowledge WHERE reference_id = ? AND facet = 'categoria' "
                                 "AND value = 'marketing_vendas'", (ref,)).fetchone()
            self.assertEqual(tuple(row), ("rejeitada_humano", "human"))

    def test_visual_model_change_and_forced_stage(self):
        with TempEngine() as t:
            e = t.engine
            s, _ = self.full(t)
            ref = s["ingest"].reference_id
            e.cfg.visual_model = "mock-visual-v2"
            self.assertEqual(sorted(e.plan(ref).enqueued), ["assemble", "classify", "export", "index", "visual_analysis"])
            e.run()
            self.assertEqual(stage_attempt_outcomes(e, ref, "assemble"), ["completed", "reused"])  # mesmas observações
            self.assertEqual(stage_attempt_outcomes(e, ref, "transcribe"), ["completed"])
            forced = e.plan(ref, force={"classify"})
            self.assertEqual(sorted(forced.enqueued), ["classify", "export", "index"])
            e.run()
            self.assertEqual(stage_attempt_outcomes(e, ref, "classify")[-1], "completed")       # forçada: não reutiliza
            self.assertEqual(stage_attempt_outcomes(e, ref, "index")[-1], "reused")

    def test_partial_failure_keeps_independent_branches_moving(self):
        with TempEngine() as t:
            e = t.engine
            outs = tool_outputs()
            outs.pop("ffprobe")
            s = seed_media_reference(e, URL, "par01", metadata=META, outputs=outs)
            ref = s["ingest"].reference_id
            done = e.run()
            st = {d["stage"]: d["outcome"] for d in done if d["stage"]}
            self.assertEqual(st["probe"], "waiting_dependency")
            for branch in ("transcribe", "scenes", "frames", "metrics", "visual_analysis"):
                self.assertEqual(st[branch], "completed", branch)
            self.assertNotIn("assemble", st)                       # bloqueada pela etapa que falta
            e.store.write_bytes("tools/par01/ffprobe.json", tool_outputs()["ffprobe"])
            e.register_artifact(ref, "ffprobe", "tools/par01/ffprobe.json", origin="tool:ffprobe")
            t.clock.advance(3600)
            e.run()
            view = e.processing(ref)
            self.assertEqual(view["ii_mm_equivalent"], "completed")
            self.assertEqual(stage_attempt_outcomes(e, ref, "probe"), ["waiting_dependency", "completed"])

    def test_metadata_only_reference_classifies_without_inventing_visual_evidence(self):
        with TempEngine() as t:
            e = t.engine
            r = e.ingest(record_from_url("https://www.youtube.com/watch?v=SYNTHmeta0001",
                                         metadata={"title": "Tutorial passo a passo de automação no n8n com CapCut", "duration_s": 61.0}))
            e.run()
            view = e.processing(r.reference_id)
            self.assertEqual(view["graph"], "metadata")
            res = I.current_result(e.conn, r.reference_id, "classify")["result"]
            self.assertTrue(set(res["categories"]) & {"tutorial", "automacao"})
            self.assertTrue(all(v in ("suggested_metadata", "hypothesis", "insufficient") for v in res["categories"].values()))
            self.assertNotIn("visually_identified", res["tools"].values())   # texto nunca vira confirmação visual

    def test_processing_view_maps_to_ii_mm_stage_names(self):
        with TempEngine() as t:
            e = t.engine
            s = seed_media_reference(e, URL, "view01", metadata=META)
            ref = s["ingest"].reference_id
            e.plan(ref)
            w = e.worker(owner="w")
            for _ in range(2):
                w.run_once()
            v = e.processing(ref)
            self.assertEqual(v["ii_mm_equivalent"], "metadata_extracted")
            self.assertEqual(v["stages"]["classify"]["status"], "waiting_dependency")
            e.run()
            v = e.processing(ref)
            self.assertEqual(v["ii_mm_equivalent"], "completed")
            self.assertTrue(v["awaiting_review"])


if __name__ == "__main__":
    unittest.main()
