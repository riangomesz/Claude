"""Modo sombra: classificador atual × classificador multimodal novo (Missão Suprema 02, Tarefa 06).

Garantias:
- Nada é gravado: as linhas legadas entram como dicts; `read_legacy_rows_readonly` abre o SQLite em
  modo `ro` (URI `mode=ro`), então qualquer tentativa de escrita falha no próprio SQLite.
- Nenhum resultado novo substitui o atual: o relatório só descreve concordâncias e divergências.
- Cada divergência traz as evidências do lado novo (IDs, trechos, termos) e a regra do lado legado.
- Sem taxa de acerto: com rótulo humano disponível, lista onde CADA classificador diverge do humano,
  para inspeção de falsos positivos e falsos negativos, sem eleger vencedor.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .classifier import Classifier
from .legacy import AUTOMATIC_EDITORIAL_SOURCES, from_instagram_item
from .obsidian_export import _esc
from .text_classifier import LEGACY_AS_FACET, LEGACY_TO_V2

USABLE_SUPPORT = {"supported_visual", "supported_measured", "mentioned_speech", "suggested_metadata"}
LegacySuggest = Callable[[str, list, str, str], Optional[dict]]


def read_legacy_rows_readonly(db_path: Path, limit: int = 500, offset_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lê `instagram_items` em modo somente leitura (paginado por id). Recusa caminho inexistente."""
    p = Path(db_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"banco não encontrado (não será criado): {p}")
    conn = sqlite3.connect(f"{p.as_uri()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        sql, args = "SELECT * FROM instagram_items", []
        if offset_id is not None:
            sql += " WHERE id > ?"
            args.append(offset_id)
        rows = conn.execute(sql + " ORDER BY id LIMIT ?", args + [int(limit)]).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def snapshot_readonly(src: Path, dst: Path) -> Dict[str, Any]:
    """Cópia consistente do catálogo pela API de backup do SQLite, abrindo a ORIGEM só para leitura.

    A origem nunca é aberta para escrita (`mode=ro`); a leitura vê só transações confirmadas e não espera
    escritores em andamento. O destino precisa ser um caminho novo. Recomendado para o modo sombra: o banco
    vivo fica exposto apenas durante a cópia, e a comparação roda sobre o snapshot.
    """
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"banco de origem não encontrado (não será criado): {src}")
    if src == dst:
        raise ValueError("destino do snapshot não pode ser a origem")
    if dst.exists():
        raise FileExistsError(f"destino já existe (não sobrescrevo): {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True)) as s, closing(sqlite3.connect(str(dst))) as d:
        s.backup(d)
        n = d.execute("SELECT COUNT(*) FROM instagram_items").fetchone()[0] if d.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='instagram_items'").fetchone() else None
    return {"snapshot": str(dst), "rows_instagram_items": n}


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    """Célula de planilha segura: texto externo começando com = + - @ não vira fórmula no Excel/LibreOffice."""
    text = "" if value is None else " ".join(str(value).split())
    return "'" + text if text[:1] in _FORMULA_PREFIXES else text


def export_review_csv(report: Dict[str, Any], path: Path) -> int:
    """Planilha de revisão das divergências (UTF-8 com BOM, para abrir certo no Excel). Colunas do revisor vazias."""
    cols = ["item_id", "tipo_divergencia", "legado_rotulo", "legado_origem", "novo_categorias", "novo_evidencias",
            "rotulo_humano_existente", "decisao_revisor", "comentario_revisor"]
    rows = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in report.get("divergences", []):
            new = "; ".join(f"{c} ({info['support']})" for c, info in d["new"].items()) or "nenhuma"
            ev = " | ".join(f"[{e['status']}] {e['claim'][:80]}" for info in d["new"].values() for e in info["evidence"][:2])
            w.writerow([_cell(x) for x in (d["item_id"], d["kind"], d["legacy"]["label"], d["legacy"]["origin"], new, ev,
                                           (d.get("human") or {}).get("label"), "", "")])
            rows += 1
    return rows


def _new_side(doc: Dict[str, Any]) -> Dict[str, Any]:
    ev = {e["evidence_id"]: e for e in doc["evidence"]}
    cats = {}
    for c in doc["categories"]:
        if c["support"] not in USABLE_SUPPORT:
            continue
        cats[c["category"]] = {
            "support": c["support"],
            "evidence": [{"evidence_id": b["evidence_id"], "status": ev[b["evidence_id"]]["status"],
                          "claim": ev[b["evidence_id"]]["claim"][:160], "terms": b.get("terms"), "tag": b.get("tag")}
                         for b in c.get("basis", []) if not b.get("contra") and b["evidence_id"] in ev],
        }
    return cats


def compare_row(row: Dict[str, Any], duration_s: Optional[float] = None, clf: Optional[Classifier] = None,
                legacy_suggest: Optional[LegacySuggest] = None) -> Dict[str, Any]:
    clf = clf or Classifier()
    n, rep = from_instagram_item(row, duration_s=duration_s or row.get("media_duration_sec") or 60.0)
    if n is None:
        return {"item_id": row.get("id"), "status": "blocked", "reason": rep.blocking}
    doc = clf.classify(n.build())
    new = _new_side(doc)
    hashtags = json.loads(row["hashtags_json"]) if isinstance(row.get("hashtags_json"), str) and row["hashtags_json"].startswith("[") else []
    if legacy_suggest is not None:
        sug = legacy_suggest(row.get("caption") or "", hashtags, row.get("owner_username") or "", row.get("post_type") or "")
        legacy_label = (sug or {}).get("suggested_category")
        legacy_origin = f"suggest_editorial_category: {(sug or {}).get('reason')}"
    else:
        src = (row.get("editorial_category_source") or "").strip().lower()
        legacy_label = row.get("editorial_category") if src in AUTOMATIC_EDITORIAL_SOURCES else None
        legacy_origin = f"editorial_category armazenada ({src or 'sem origem'})"
    human_src = (row.get("editorial_category_source") or "").strip().lower()
    human_label = row.get("editorial_category") if human_src not in AUTOMATIC_EDITORIAL_SOURCES else None

    mapped = LEGACY_TO_V2.get(legacy_label) if legacy_label else None
    ai_terms = doc.get("topic_facets", {}).get("ai_terms", [])
    if legacy_label in LEGACY_AS_FACET:
        kind = "agree" if ai_terms or mapped in new else "only_legacy"
    elif mapped is None and not new:
        kind = "agree_none"
    elif mapped is None:
        kind = "only_new"
    elif mapped in new:
        kind = "agree" if len(new) == 1 else "agree_plus_new"
    elif not new:
        kind = "only_legacy"
    else:
        kind = "different"
    out = {"item_id": row.get("id"), "status": "compared", "kind": kind,
           "legacy": {"label": legacy_label, "mapped": mapped, "origin": legacy_origin,
                      "curation_category": row.get("curation_category"), "curation_rule": row.get("curation_rule")},
           "new": new, "ai_terms": ai_terms, "adapter_warnings": rep.warnings}
    if human_label:
        hm = LEGACY_TO_V2.get(human_label)
        out["human"] = {"label": human_label, "mapped": hm,
                        "legacy_matches_human": legacy_label == human_label if legacy_label else None,
                        "new_matches_human": (hm in new) if hm else None,
                        "new_extra_vs_human": sorted(set(new) - {hm}) if hm else sorted(new)}
    return out


def run_shadow(rows: Iterable[Dict[str, Any]], legacy_suggest: Optional[LegacySuggest] = None,
               durations: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    clf = Classifier()
    items = [compare_row(r, (durations or {}).get(r.get("id")), clf, legacy_suggest) for r in rows]
    kinds: Dict[str, int] = {}
    for it in items:
        k = it.get("kind", "blocked")
        kinds[k] = kinds.get(k, 0) + 1
    with_human = [i for i in items if i.get("human")]
    report = {
        "schema_version": "ii.shadow_report.v1",
        "writes_performed": 0,
        "totals": {"rows": len(items), **kinds},
        "divergences": [i for i in items if i.get("kind") in ("only_legacy", "only_new", "different", "agree_plus_new")],
        "blocked": [i for i in items if i["status"] == "blocked"],
        "human_reference": {
            "rows_with_human_label": len(with_human),
            "legacy_diverges_from_human": [i["item_id"] for i in with_human if i["human"]["legacy_matches_human"] is False],
            "new_misses_human_label": [i["item_id"] for i in with_human if i["human"]["new_matches_human"] is False],
            "new_adds_beyond_human": [i["item_id"] for i in with_human if i["human"]["new_extra_vs_human"]],
        },
        "caveat": ("Relatório descritivo. Sem rótulo humano não há como dizer qual classificador acerta; "
                   "mesmo com rótulos, contagens de amostra pequena ou sintética não são taxa de acerto."),
        "items": items,
    }
    return report


def render_markdown(report: Dict[str, Any], max_items: int = 50) -> str:
    t = report["totals"]
    lines = ["# Relatório do modo sombra", "", f"_{report['caveat']}_", "", "## Totais", ""]
    lines += [f"- {k}: {v}" for k, v in t.items()]
    lines += ["", "## Divergências (com evidências)", ""]
    for d in report["divergences"][:max_items]:
        lines.append(f"### {_esc(d['item_id'])} — {d['kind']}")
        lines.append(f"- Atual: {_esc(d['legacy']['label'] or '—')} ({_esc(d['legacy']['origin'])})")
        for cat, info in d["new"].items():
            ev = "; ".join(f"[{e['status']}] {_esc(e['claim'][:80])}" + (f" (termos: {_esc(', '.join(e['terms']))})" if e.get("terms") else "") for e in info["evidence"][:3])
            lines.append(f"- Novo: {cat} ({info['support']}): {ev}")
        if not d["new"]:
            lines.append("- Novo: nenhuma categoria sustentada")
        lines.append("")
    h = report["human_reference"]
    lines += ["## Inspeção contra rótulo humano", "", f"- Linhas com rótulo humano: {h['rows_with_human_label']}",
              f"- Atual diverge do humano: {_esc(', '.join(map(str, h['legacy_diverges_from_human']))) or 'nenhuma'}",
              f"- Novo não contém o rótulo humano (possível falso negativo): {_esc(', '.join(map(str, h['new_misses_human_label']))) or 'nenhuma'}",
              f"- Novo adiciona categorias além do humano (possível falso positivo ou multi-rótulo): {_esc(', '.join(map(str, h['new_adds_beyond_human']))) or 'nenhuma'}", ""]
    return "\n".join(lines)
