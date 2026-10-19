"""Relatório de compatibilidade entre os contratos do ii_mm e o código ATUAL do Projeto-MVP.

Uso:
    python -X utf8 tools/compat_report.py --projeto <pasta do Projeto-MVP> [--out relatorio_compat.json]
    python -X utf8 tools/compat_report.py --projeto <clone c6845a4> --write-baseline   (só quem mantém o pacote)

Somente leitura no projeto: assinaturas por AST (nada é importado de lá); colunas de `instagram_items`
obtidas montando o esquema legado num banco temporário, num subprocesso, sobre uma CÓPIA de core/ e config/.
Compara com `handoff/baseline_contratos_c6845a4.json` e classifica cada item: igual, alterado, ausente, novo.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BASELINE = HERE / "handoff" / "baseline_contratos_c6845a4.json"
MODULES = ["core/curation.py", "core/content_miner.py", "core/vision_client.py", "core/scene_analyzer.py", "core/transcription.py",
           "core/audio_processor.py", "core/instagram_importer.py", "core/account_connection.py", "core/studio_adapter.py",
           "core/media_acquisition.py", "core/trash_manager.py", "temporal_intelligence/metric_calculator.py",
           "temporal_intelligence/transition_detector.py"]
SAFE_DIRS = ("core", "config")


def signatures(projeto: Path) -> dict:
    out = {}
    for rel in MODULES:
        p = projeto / rel
        if not p.is_file():
            out[rel] = None
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        items = {}
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
                items[f"def {n.name}"] = [a.arg for a in n.args.args] + [f"*{a.arg}" for a in n.args.kwonlyargs]
            elif isinstance(n, ast.ClassDef):
                items[f"class {n.name}"] = [s.target.id for s in n.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
        out[rel] = items
    return out


def literal_values(projeto: Path) -> dict:
    """Valores que os adaptadores assumem: decisões de triagem válidas e origem padrão da categoria editorial."""
    vals = {"triage_valid_decisions": None, "editorial_source_default_server": None, "editorial_source_default_function": None}
    cur = projeto / "core" / "curation.py"
    if cur.is_file():
        t = cur.read_text(encoding="utf-8")
        m = re.search(r"valid_decisions\s*=\s*\{([^}]*)\}", t)
        vals["triage_valid_decisions"] = sorted(re.findall(r"[\"']([a-z_]+)[\"']", m.group(1))) if m else None
        m = re.search(r"def update_editorial_category\([^)]*source:\s*str\s*=\s*[\"']([a-z_]+)[\"']", t, re.S)
        vals["editorial_source_default_function"] = m.group(1) if m else None
    srv = projeto / "core" / "review_server.py"
    if srv.is_file():
        m = re.search(r"payload\.get\(\s*[\"']source[\"']\s*,\s*[\"']([a-z_]+)[\"']\s*\)", srv.read_text(encoding="utf-8"))
        vals["editorial_source_default_server"] = m.group(1) if m else None
    return vals


def instagram_columns(projeto: Path) -> list:
    """Monta o esquema legado num banco temporário a partir de uma cópia de core/ e config/, em subprocesso."""
    with tempfile.TemporaryDirectory(prefix="ii_compat_") as t:
        copy = Path(t) / "mvp"
        for d in SAFE_DIRS:
            if (projeto / d).is_dir():
                shutil.copytree(projeto / d, copy / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite*", "*.db"))
        script = (f"import sys, sqlite3; sys.path.insert(0, {str(HERE)!r}); from pathlib import Path; "
                  f"from ii_mm.db.legacy_fixture import build_legacy_catalog; db = Path({str(Path(t) / 'c.sqlite')!r}); "
                  f"build_legacy_catalog(db, Path({str(copy)!r})); c = sqlite3.connect(str(db)); "
                  "print('\\n'.join(r[1] for r in c.execute('PRAGMA table_info(instagram_items)'))); c.close()")
        r = subprocess.run([sys.executable, "-W", "ignore", "-c", script], capture_output=True, text=True, encoding="utf-8",
                           timeout=180, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if r.returncode != 0:
            return [f"ERRO: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'falha ao montar esquema'}"]
        return sorted(x for x in r.stdout.split() if x)


def collect(projeto: Path) -> dict:
    return {"signatures": signatures(projeto), "instagram_items_columns": instagram_columns(projeto), "values": literal_values(projeto)}


def compare(base: dict, cur: dict) -> dict:
    rep = {"modules": {}, "columns": {}, "values": {}, "summary": {"igual": 0, "alterado": 0, "ausente": 0, "novo": 0}}
    for mod, items in base["signatures"].items():
        now = cur["signatures"].get(mod)
        if now is None:
            rep["modules"][mod] = {"status": "ausente"}
            rep["summary"]["ausente"] += 1
            continue
        diff = {}
        for k, v in (items or {}).items():
            if k not in now:
                diff[k] = "ausente"
            elif now[k] != v:
                diff[k] = {"antes": v, "agora": now[k]}
        new = sorted(set(now) - set(items or {}))
        status = "igual" if not diff and not new else "alterado" if diff else "novo"
        rep["modules"][mod] = {"status": status, "mudancas": diff, "novos": new}
        rep["summary"][status] += 1
    b, c = set(base["instagram_items_columns"]), set(cur["instagram_items_columns"])
    rep["columns"] = {"removidas": sorted(b - c), "novas": sorted(c - b), "total_atual": len(c)}
    rep["values"] = {k: {"baseline": base["values"].get(k), "atual": cur["values"].get(k),
                         "status": "igual" if base["values"].get(k) == cur["values"].get(k) else "alterado"} for k in base["values"]}
    actions = []
    if rep["columns"]["novas"]:
        actions.append("colunas novas em instagram_items: classificar em legacy.INSTAGRAM_ITEM_MAPPING ou LEGACY_PRESERVED")
    if rep["columns"]["removidas"]:
        actions.append("colunas removidas: revisar o adaptador from_instagram_item")
    for mod, info in rep["modules"].items():
        if info["status"] in ("alterado", "ausente"):
            actions.append(f"{mod}: assinatura mudou ou sumiu; reconferir a linha correspondente da MATRIZ_COMPATIBILIDADE")
    for k, v in rep["values"].items():
        if v["status"] == "alterado":
            actions.append(f"valor '{k}' mudou: revisar legacy.HUMAN_EDITORIAL_SOURCES / AUTOMATIC_EDITORIAL_SOURCES")
    rep["acoes"] = actions
    rep["compativel_com_baseline"] = not actions
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projeto", required=True)
    ap.add_argument("--out")
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)
    projeto = Path(a.projeto).resolve()
    cur = collect(projeto)
    if a.write_baseline:
        BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline gravada: {BASELINE}")
        return 0
    rep = compare(json.loads(BASELINE.read_text(encoding="utf-8")), cur)
    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.out:
        out = Path(a.out).resolve()
        if out.is_relative_to(projeto):
            raise SystemExit("recusado: o relatório não pode ser gravado dentro do Projeto-MVP")
        out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"compativel_com_baseline": rep["compativel_com_baseline"], "resumo": rep["summary"],
                      "colunas": {k: rep["columns"][k] for k in ("removidas", "novas")}, "acoes": rep["acoes"]}, ensure_ascii=False, indent=2))
    return 0 if rep["compativel_com_baseline"] else 1


if __name__ == "__main__":
    sys.exit(main())
