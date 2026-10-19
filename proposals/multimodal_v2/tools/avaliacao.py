"""Avaliação humana a partir do modo sombra (Missão Suprema 03, Etapa 12). Ver AVALIACAO_HUMANA.md.

Uso:
    python -X utf8 tools/avaliacao.py amostra      --sombra <pasta sombra> --out <planilha.csv> [--n 40] [--seed 20261019] [--nao-cega]
    python -X utf8 tools/avaliacao.py concordancia --sombra <pasta sombra> --rotulos <planilha preenchida.csv> --out <concordancia.json>

Lê `relatorio_sombra.json` e, se existir, `snapshot_catalogo.sqlite` (só leitura, para mostrar URL e legenda
ao revisor). Nunca sobrescreve arquivo existente. Não calcula nada sem rótulo humano.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ii_mm.evaluation import (LabelError, agreement_report, export_labeling_sheet, load_labels,  # noqa: E402
                              predictions_from_shadow, select_sample)


def _rows_from_snapshot(sombra: Path, ids) -> dict:
    snap = sombra / "snapshot_catalogo.sqlite"
    if not snap.is_file() or not ids:
        return {}
    with closing(sqlite3.connect(f"{snap.resolve().as_uri()}?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        cols = {r["name"] for r in c.execute("PRAGMA table_info(instagram_items)")}
        wanted = [x for x in ("id", "url", "caption") if x in cols]
        q = f"SELECT {', '.join(wanted)} FROM instagram_items WHERE id IN ({', '.join('?' * len(ids))})"
        return {r["id"]: dict(r) for r in c.execute(q, list(ids))}


def _new_file(path: str) -> Path:
    p = Path(path).resolve()
    if p.exists():
        raise SystemExit(f"recusado: {p} já existe (não sobrescrevo)")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("amostra")
    a1.add_argument("--sombra", required=True)
    a1.add_argument("--out", required=True)
    a1.add_argument("--n", type=int, default=40)
    a1.add_argument("--seed", type=int, default=20261019)
    a1.add_argument("--nao-cega", action="store_true", help="mostra as sugestões dos classificadores (ancora o revisor)")
    a2 = sub.add_parser("concordancia")
    a2.add_argument("--sombra", required=True)
    a2.add_argument("--rotulos", required=True)
    a2.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    sombra = Path(a.sombra).resolve()
    report = json.loads((sombra / "relatorio_sombra.json").read_text(encoding="utf-8"))
    if a.cmd == "amostra":
        out = _new_file(a.out)
        sample = select_sample(report.get("items", []), n=a.n, seed=a.seed)
        rows = _rows_from_snapshot(sombra, sample["selected"])
        n = export_labeling_sheet(sample, out, rows, blind=not a.nao_cega)
        meta = out.with_suffix(".amostra.json")
        if meta.exists():
            raise SystemExit(f"recusado: {meta} já existe (não sobrescrevo)")
        meta.write_text(json.dumps({k: sample[k] for k in ("seed", "requested", "selected", "strata", "warnings")},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"planilha: {out} ({n} itens; {'cega' if not a.nao_cega else 'NÃO cega'}) | registro da amostra: {meta}")
        for w in sample["warnings"]:
            print(f"aviso: {w}")
        return 0

    out = _new_file(a.out)
    try:
        labels = load_labels(Path(a.rotulos))
    except LabelError as exc:
        print(f"planilha com erros de preenchimento: {exc}")
        return 1
    if not labels:
        print("nenhum item rotulado: nada a calcular")
        return 1
    rep = agreement_report(labels, predictions_from_shadow(report))
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"itens rotulados: {rep['n_labeled']} | relatório: {out}")
    if rep.get("warning"):
        print(f"aviso: {rep['warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
