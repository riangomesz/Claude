"""Modo sombra para o Antigravity (Estágio 2). Somente leitura no catálogo legado.

    python -X utf8 handoff/exemplo_uso.py --legacy-db <catalog.sqlite> --out <pasta de trabalho fora do Vault> [--limit 200]
    python -X utf8 handoff/exemplo_uso.py --demo --out <pasta>          (sem banco: fixtures sintéticas)

O que faz:
1. Por padrão tira um SNAPSHOT do catálogo pela API de backup do SQLite, abrindo a origem em `mode=ro`
   (o banco vivo só é lido durante a cópia; nada é escrito nele). `--no-snapshot` lê a origem direto, também `ro`.
2. Roda o classificador atual (rótulos armazenados) ao lado do novo, sem gravar nada em banco algum.
3. Escreve em --out: relatorio_sombra.json, relatorio_sombra.md e revisao_divergencias.csv (para o curador).
Não altera curadoria, não chama rede nem modelos. --out não pode ser um Vault do Obsidian nem já conter um snapshot.
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
from ii_mm.shadow import export_review_csv, read_legacy_rows_readonly, render_markdown, run_shadow, snapshot_readonly  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-db")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--no-snapshot", action="store_true", help="ler a origem diretamente (mode=ro), sem cópia")
    a = ap.parse_args(argv)
    out = assert_staging(Path(a.out))
    out.mkdir(parents=True, exist_ok=True)
    if a.demo:
        rows = json.loads((HERE / "fixtures" / "legacy" / "shadow_rows.json").read_text(encoding="utf-8"))
        source = "fixtures sintéticas"
    elif a.legacy_db:
        db = Path(a.legacy_db)
        if not a.no_snapshot:
            info = snapshot_readonly(db, out / "snapshot_catalogo.sqlite")
            print(f"snapshot: {info['snapshot']} ({info['rows_instagram_items']} linhas)")
            db = Path(info["snapshot"])
        rows = read_legacy_rows_readonly(db, limit=a.limit)
        source = str(Path(a.legacy_db).resolve())
    else:
        ap.error("informe --legacy-db ou --demo")
    report = run_shadow(rows)
    report["source"] = source
    (out / "relatorio_sombra.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "relatorio_sombra.md").write_text(render_markdown(report), encoding="utf-8")
    n = export_review_csv(report, out / "revisao_divergencias.csv")
    print(json.dumps(report["totals"], ensure_ascii=False))
    print(f"divergências para revisão: {n} (revisao_divergencias.csv)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
