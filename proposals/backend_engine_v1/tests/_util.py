"""Utilidades de teste: motor em pasta temporária com relógio manual."""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ii_be.clock import FakeClock  # noqa: E402
from ii_be.engine import Engine  # noqa: E402
from ii_be.errors import RetryPolicy  # noqa: E402

FIX = ROOT / "fixtures"


class TempEngine:
    """Contexto com Engine em arquivo (WAL), raiz de artefatos e staging temporários."""

    def __init__(self, memory: bool = False, **kw):
        self.memory, self.kw = memory, kw

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ii_be_test_"))
        self.clock = self.kw.pop("clock", None) or FakeClock()
        policy = self.kw.pop("policy", None) or RetryPolicy(jitter=0.0)
        db = ":memory:" if self.memory else str(self.dir / "engine.sqlite")
        self.engine = Engine(db, root=self.dir / "store", export_dir=self.dir / "staging", clock=self.clock, policy=policy, **self.kw)
        return self

    def __exit__(self, *exc):
        self.engine.close()
        shutil.rmtree(self.dir, ignore_errors=True)
