"""Sobe a API local do motor criativo com especialistas MOCK (nenhuma chamada externa). Só loopback.

  python -X utf8 -m ii_ce.serve --db CAMINHO/engine.sqlite --root CAMINHO/store --out dossies --staging obsidian_staging [--port 8777]

Use uma CÓPIA do banco do ii_be: a primeira execução cria as tabelas `ce_*` (aditivo) no mesmo arquivo."""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from . import _be  # noqa: F401
from ii_be.engine import Engine
from .api import CreativeAPI, serve
from .orchestrator import CreativeEngine
from .providers import MockSpecialist
from .contracts import SPECIALISTS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--root", required=True, help="raiz de artefatos do ii_be (mídia e saídas de ferramentas)")
    ap.add_argument("--out", default="dossies")
    ap.add_argument("--staging", default="obsidian_staging")
    ap.add_argument("--port", type=int, default=8777)
    a = ap.parse_args(argv)
    if not Path(a.db).is_file():
        print(f"banco não encontrado: {a.db}", file=sys.stderr)
        return 2

    def factory() -> CreativeEngine:
        eng = Engine(a.db, root=Path(a.root))
        return CreativeEngine(engine=eng, providers={s: MockSpecialist(s) for s in SPECIALISTS})
    srv, th = serve(CreativeAPI(factory, Path(a.out), Path(a.staging)), "127.0.0.1", a.port)
    print(f"ii.ce.api.v1 em http://127.0.0.1:{srv.server_address[1]} (especialistas MOCK; Ctrl+C encerra)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
