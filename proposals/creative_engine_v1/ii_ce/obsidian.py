"""Exportação para STAGING do Obsidian (nunca o cofre real). Reutiliza do `ii_mm` a trava de cofre e a escrita atômica idempotente.

Gera uma nota por referência (`creative/<ref>.md`) com frontmatter estável, links internos e entre vídeos (mesma ferramenta ou técnica),
mais notas-índice de ferramenta e de técnica. O bloco de curadoria humana (marcadores do `ii_mm`) e as chaves `curador_*` são preservados
entre reexportações. Texto externo é escapado: não consegue fechar o bloco de curadoria nem injetar frontmatter."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from . import _be  # noqa: F401
from ii_mm.obsidian_export import CUR_END, CUR_START, DEFAULT_CURATION, _write_if_changed, assert_staging, safe_name
from .contracts import GENERATOR_VERSION, clean_text, slug_key

_BLOCK = re.compile(re.escape(CUR_START) + r"(.*?)" + re.escape(CUR_END), re.S)


def _y(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _preserved(path: Path) -> str:
    if path.exists():
        m = _BLOCK.search(path.read_text(encoding="utf-8"))
        if m:
            return m.group(1).strip("\n")
    return DEFAULT_CURATION


def _related(conn, ref: str, keys: List[str]) -> List[str]:
    if not keys:
        return []
    marks = ",".join("?" * len(keys))
    rows = conn.execute(f"SELECT DISTINCT i.reference_id FROM ce_groups g JOIN ce_investigations i ON i.investigation_id = g.investigation_id "
                        f"WHERE g.key IN ({marks}) AND i.reference_id != ? AND i.state != 'superseded' ORDER BY i.reference_id", [*keys, ref]).fetchall()
    return [r["reference_id"] for r in rows]


def export_investigation(ce, inv_id: str, staging: Path) -> Dict[str, Any]:
    staging = assert_staging(Path(staging))
    inv = ce.get(inv_id)
    ref = inv["bundle"]["reference_id"]
    groups = [g for g in ce.groups(inv_id) if g.get("human_state") != "rejected"]
    tools = sorted({g["key"].split(":", 1)[1] for g in groups if g["key"].startswith("ferramenta:")})
    techs = sorted({g["key"].split(":", 1)[1] for g in groups if g["key"].startswith("tecnica:")})
    cats = sorted({c["category"] for c in inv["bundle"]["facets"].get("categories", []) if c["support"] != "insufficient"})
    related = _related(ce.conn, ref, [f"ferramenta:{t}" for t in tools] + [f"tecnica:{t}" for t in techs])
    dos = ce.conn.execute("SELECT version, content_hash FROM ce_dossiers WHERE investigation_id = ? ORDER BY version DESC LIMIT 1", (inv_id,)).fetchone()
    path = staging / "creative" / f"{safe_name(ref)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"id: {_y('ce_' + ref)}", f"reference_id: {_y(ref)}", f"investigation_id: {_y(inv_id)}", f"investigation_seq: {inv['seq']}",
          f"estado: {_y(inv['state'])}", f"dossie_versao: {dos['version'] if dos else 'null'}", f"gerador: {_y(GENERATOR_VERSION)}",
          f"versoes_processadores: {_y(inv['versions'])}", f"proveniencia: {_y('ii_ce sobre ii_be/ii_mm; afirmações com evidência; ver dossiê')}",
          "tags: " + _y(["instagram-intelligence", "creative-engine"] + [f"categoria/{c}" for c in cats] + [f"ferramenta/{slug_key(t)}" for t in tools] + [f"tecnica/{t}" for t in techs]),
          "categorias: " + _y(cats), "ferramentas: " + _y(tools), "tecnicas: " + _y(techs), "---", ""]
    body = [f"# Investigação criativa · {ref}", "", f"Nota do `ii_mm` (análise): [[{safe_name(ref)}]]", "", "## Afirmações por estado", ""]
    for g in groups:
        body.append(f"- **{g['state']}** `{g['key']}` — {clean_text(g['summary'], 240).replace('[[', '‹‹').replace('<!--', '')}")
    body += ["", "## Ferramentas", "", *(f"- [[ferramenta-{slug_key(t)}]]" for t in tools), "", "## Técnicas", "", *(f"- [[tecnica-{t}]]" for t in techs), "",
             "## Vídeos relacionados (mesma ferramenta ou técnica)", "", *(f"- [[{safe_name(r)}]]" for r in related), "" if related else "_Nenhum ainda._", "",
             "## Curadoria humana", "", CUR_START, _preserved(path), CUR_END, ""]
    results = {"note": _write_if_changed(path, "\n".join(fm + body))}
    for kind, items in (("ferramenta", tools), ("tecnica", techs)):
        for it in items:
            hub = staging / "creative" / f"{kind}-{slug_key(it)}.md"
            refs = sorted({r["reference_id"] for r in ce.conn.execute(
                "SELECT DISTINCT i.reference_id FROM ce_groups g JOIN ce_investigations i ON i.investigation_id = g.investigation_id WHERE g.key = ? AND i.state != 'superseded'", (f"{kind}:{it}",))})
            hub_text = "\n".join(["---", f"id: {_y(f'{kind}-{slug_key(it)}')}", f"tags: {_y(['instagram-intelligence', kind + '/' + slug_key(it)])}", "---", "", f"# {kind.capitalize()} · {it}", "",
                                  "Referências com esta " + kind + ":", "", *(f"- [[{safe_name(r)}]]" for r in refs), ""])
            results[f"{kind}:{it}"] = _write_if_changed(hub, hub_text)
    from . import events as EV
    from ii_be.db import tx
    with tx(ce.conn) as c:
        EV.emit(c, "obsidian.exported", inv_id, {"notes": len(results)}, ce.clock.now(), f"{inv_id}|obsidian|{dos['content_hash'] if dos else 'sem-dossie'}")
    return {"investigation_id": inv_id, "path": str(path), "results": results, "related": related}
