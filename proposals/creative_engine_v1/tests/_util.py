"""Utilidades de teste: motor ii_be + CreativeEngine em pasta temporária, relógio manual e provedores roteirizados."""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ii_ce import _be  # noqa: E402,F401
from ii_be.clock import FakeClock  # noqa: E402
from ii_be.engine import Engine  # noqa: E402
from ii_be.errors import RetryPolicy  # noqa: E402
from ii_be.synthetic import seed_media_reference  # noqa: E402
from ii_ce.orchestrator import CreativeEngine  # noqa: E402
from ii_ce.providers import MockSpecialist, SpecialistProvider  # noqa: E402
from ii_ce.contracts import SCHEMA_RESULT  # noqa: E402

SPECS = ("audiovisual", "reproducao", "criativo", "implementacao")


def mocks(**overrides):
    return {s: overrides.get(s) or MockSpecialist(s) for s in SPECS}


class Env:
    """with Env() as e: e.engine, e.ce, e.ref (referência analisada), e.dir"""

    def __init__(self, providers=None, analysed=True, caption="Fluxo de automação com n8n e motion", seed="t1", **ce_kw):
        self.providers, self.analysed, self.caption, self.seed, self.ce_kw = providers, analysed, caption, seed, ce_kw

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ii_ce_test_"))
        self.clock = FakeClock()
        self.engine = Engine(str(self.dir / "e.sqlite"), root=self.dir / "store", export_dir=self.dir / "stg", clock=self.clock, policy=RetryPolicy(jitter=0.0))
        self.ref = self.add_reference(self.seed, self.caption, self.analysed)
        self.ce = CreativeEngine(engine=self.engine, providers=self.providers if self.providers is not None else mocks(), clock=self.clock, **self.ce_kw)
        return self

    def add_reference(self, seed, caption, analysed=True):
        r = seed_media_reference(self.engine, f"https://www.instagram.com/reel/SYNTH{seed}/", seed, metadata={"caption": caption})["ingest"].reference_id
        if analysed:
            self.engine.run()
        return r

    def new_ce(self, providers=None, conn=None, **kw):
        return CreativeEngine(engine=None if conn else self.engine, conn=conn, providers=providers or mocks(), clock=self.clock, **kw)

    def __exit__(self, *exc):
        self.engine.close()
        shutil.rmtree(self.dir, ignore_errors=True)


class Scripted(SpecialistProvider):
    """Devolve afirmações roteirizadas (função do pacote) e grava o que recebeu."""
    name = "scripted"

    def __init__(self, specialist, fn):
        self.specialist, self.fn, self.seen = specialist, fn, []

    def call(self, instructions, data, request, cancel):
        self.seen.append((instructions, data))
        return {"schema_version": SCHEMA_RESULT, "task_id": request["task_id"], "specialist": self.specialist, "claims": self.fn(data),
                "open_questions": [], "usage": {"usd": 0}, "provenance": {"provider": self.name, "mock": True}}
