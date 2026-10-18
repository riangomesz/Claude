"""Exemplo de uso para o Antigravity (Estágio 2: modo sombra). Somente leitura no banco legado.

    python3 handoff/exemplo_uso.py --legacy-db <caminho do catalog.sqlite> --out <pasta de saída fora do Vault> [--limit 200]
    python3 handoff/exemplo_uso.py --demo --out <pasta>      (sem banco: usa fixtures sintéticas)

O que faz:
1. Lê `instagram_items` em modo `ro` (o SQLite recusa qualquer escrita).
2. Roda o classificador atual (rótulos armazenados) ao lado do novo, SEM gravar nada no banco.
3. Escreve `relatorio_sombra.json` e `relatorio_sombra.md` na pasta --out (que não pode ser um Vault).
Não cria banco novo, não altera curadoria, não chama rede nem modelos.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from ii_mm.obsidian_export import assert_staging  # noqa: E402
from ii_mm.shadow import read_legacy_rows_readonly, render_markdown, run_shadow  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-db")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    out = assert_staging(Path(a.out))
    out.mkdir(parents=True, exist_ok=True)
    if a.demo:
        rows = json.loads((HERE / "fixtures" / "legacy" / "shadow_rows.json").read_text(encoding="utf-8"))
    elif a.legacy_db:
        rows = read_legacy_rows_readonly(Path(a.legacy_db), limit=a.limit)
    else:
        ap.error("informe --legacy-db ou --demo")
    report = run_shadow(rows)
    (out / "relatorio_sombra.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "relatorio_sombra.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
