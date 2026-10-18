"""Exportação para Obsidian em pasta de STAGING (Tarefa 15).

- Nunca escreve num cofre real: recusa caminhos dentro de uma pasta que contenha `.obsidian/`
  ou cujo caminho mencione "Obsidian Vault".
- Idempotente: conteúdo igual = arquivo intocado (devolve "unchanged"); escrita atômica (tmp + replace).
- Preserva a curadoria humana: o bloco entre os marcadores `ii:curadoria` e as chaves de frontmatter
  prefixadas com `curador_` sobrevivem a reexportações.
- Texto vindo de transcrição/legenda é escapado: não consegue fechar o bloco de curadoria nem injetar frontmatter.
- Sem timestamp de geração no corpo (isso quebraria a idempotência); a versão é o hash da análise.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .contract import assert_valid, canonical_json
from .dedup import analysis_input_hash
from .narrative import coverage
from .techniques import open_questions

CUR_START = "<!-- ii:curadoria:inicio -->"
CUR_END = "<!-- ii:curadoria:fim -->"
DEFAULT_CURATION = "_Espaço do curador: notas aqui são preservadas em reexportações._"
STATUS_LABEL = {
    "observed_visual": "visto no frame", "measured_signal": "medido", "transcript_claim": "dito na fala",
    "metadata_claim": "na legenda/metadados", "inference": "inferência", "unverified": "não verificado",
}
SUPPORT_LABEL = {
    "supported_visual": "sustentado por evidência visual", "supported_measured": "sustentado por medição",
    "mentioned_speech": "mencionado na fala", "suggested_metadata": "sugerido por metadados",
    "hypothesis": "hipótese", "insufficient": "insuficiente",
}


class ExportError(RuntimeError):
    pass


def assert_staging(path: Path) -> Path:
    p = Path(path).resolve()
    if "obsidian vault" in str(p).lower():
        raise ExportError(f"recusado: caminho parece um cofre do Obsidian: {p}")
    for d in (p, *p.parents):
        if (d / ".obsidian").is_dir():
            raise ExportError(f"recusado: {d} é um cofre do Obsidian (.obsidian/ encontrado)")
    return p


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_name(reference_id: str) -> str:
    """Nome de arquivo seguro e sem colisão em sistemas que ignoram maiúsculas (NTFS, APFS padrão).

    Shortcodes do Instagram diferenciam maiúsculas: se o ID tem maiúscula, foi alterado pela limpeza
    ou é nome reservado do Windows, recebe sufixo com hash do ID exato.
    """
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", reference_id).strip("._")[:120]
    if not name:
        raise ExportError("reference_id não gera nome de arquivo válido")
    reserved = name.split(".")[0].upper() in WINDOWS_RESERVED
    if name != reference_id or name != name.lower() or reserved:
        name = f"{'_' if reserved else ''}{name}_{hashlib.sha256(reference_id.encode('utf-8')).hexdigest()[:8]}"
    return name


_MD_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("|", "\\|"), ("[", "\\["), ("]", "\\]"),
               ("`", "'"), ("*", "\\*"), ("_", "\\_"))


def _esc(text: Any) -> str:
    """Texto externo (fala, legenda, observação) vira texto puro: sem HTML, imagem remota, wikilink ou código."""
    t = " ".join(str(text if text is not None else "").split())
    for a, b in _MD_ESCAPES:
        t = t.replace(a, b)
    return t


def _ts(t: Optional[float]) -> str:
    if t is None:
        return "—"
    m, s = divmod(float(t), 60)
    return f"{int(m):02d}:{s:06.3f}"


def _split_existing(text: str) -> Tuple[Dict[str, str], Optional[str]]:
    keep: Dict[str, str] = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if line.startswith("curador_") and ":" in line:
                    k, v = line.split(":", 1)
                    keep[k.strip()] = v.strip()
    m = re.search(re.escape(CUR_START) + r"\n?(.*?)\n?" + re.escape(CUR_END), text, re.S)
    return keep, (m.group(1) if m else None)


def render(doc: Dict[str, Any], curation: Optional[str] = None, curator_keys: Optional[Dict[str, str]] = None) -> str:
    ref, video = doc["reference"], doc["video"]
    ev = {e["evidence_id"]: e for e in doc["evidence"]}
    fm = [
        "---",
        f"ii_reference_id: {json.dumps(ref['reference_id'])}",
        f"ii_platform: {ref['platform']}",
        f"ii_schema: {doc['schema_version']}",
        f"ii_analysis_hash: {analysis_input_hash(doc)[:16]}",
        "ii_categories: " + json.dumps([c["category"] for c in doc["categories"] if c.get("review_state") != "rejected"]),
        "ii_tools: " + json.dumps(sorted(t["name"] for t in doc["tools"]), ensure_ascii=False),
    ]
    fm += [f"{k}: {v}" for k, v in sorted((curator_keys or {}).items())]
    fm.append("---")
    out: List[str] = fm + ["", f"# Referência {_esc(ref['reference_id'])}", "", "## Identificação", ""]
    out += [f"- Plataforma: {ref['platform']}", f"- Vídeo: `{_esc(video['video_id'])}` ({video['duration_s']} s)"]
    if ref.get("origin_url"):
        out.append(f"- Origem: {_esc(ref['origin_url'])}")
    if ref.get("author_handle"):
        out.append(f"- Autor (informado nos metadados): {_esc(ref['author_handle'])}")
    if video.get("content_sha256"):
        out.append(f"- SHA-256 do conteúdo: `{video['content_sha256'][:16]}…`")

    counts: Dict[str, int] = {}
    for e in doc["evidence"]:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    out += ["", "## Resumo", "", "Resumo factual gerado das evidências (não é interpretação):", ""]
    out += [f"- {n} evidência(s) {STATUS_LABEL[s]}" for s, n in sorted(counts.items(), key=lambda kv: list(STATUS_LABEL).index(kv[0]))] or ["- Sem evidências."]

    out += ["", "## Categorias", "", "| Categoria | Apoio | Revisão | Evidências (tempo) |", "|---|---|---|---|"]
    for c in doc["categories"]:
        times = ", ".join(sorted({_ts(ev[i]["t_start_s"]) for i in c.get("evidence_ids", []) if i in ev})) or "—"
        flag = " (contestada)" if c.get("contested") else ""
        out.append(f"| {c['category']}{flag} | {SUPPORT_LABEL[c['support']]} | {c.get('review_state', 'pending')} | {times} |")
    if not doc["categories"]:
        out.append("| — | — | — | — |")

    out += ["", "## Ferramentas", ""]
    out += [f"- {_esc(t['name'])}: {t['status']}" + (f" (corrigido de {_esc(t['corrected_from'])})" if t.get("corrected_from") else "")
            for t in doc["tools"]] or ["- Nenhuma ferramenta identificada."]

    out += ["", "## Estrutura narrativa", ""]
    blocks = doc.get("narrative_blocks", [])
    out += [f"- {_ts(b['t_start_s'])}–{_ts(b['t_end_s'])} **{b['type']}** ({SUPPORT_LABEL.get(b.get('support'), b.get('support'))}, {b['status']})"
            for b in blocks] or ["- Nenhum bloco registrado."]
    if blocks:
        cov = coverage(doc)
        out.append(f"- Tipos ausentes: {', '.join(cov['missing_types']) or 'nenhum'}")

    out += ["", "## Técnicas audiovisuais", ""]
    techs = [t for t in doc.get("techniques", []) if t["level"] != "reproduction_suggestion"]
    out += [f"- **{t['technique']}** — {t['level']}: prova {t.get('proves', '—')}; não prova {t.get('does_not_prove', '—')}"
            for t in techs] or ["- Nenhuma técnica registrada."]

    out += ["", "## Evidências temporais", ""]
    timed = sorted((e for e in doc["evidence"] if e.get("t_start_s") is not None), key=lambda e: (e["t_start_s"], e["evidence_id"]))
    out += [f"- `{_ts(e['t_start_s'])}` [{STATUS_LABEL[e['status']]}] {_esc(e['claim'])[:240]}" + (f" (ref {_esc(e['ref'])})" if e.get("ref") else "")
            for e in timed] or ["- Nenhuma evidência com tempo."]

    out += ["", "## Ideias de reprodução", ""]
    ideas = [(t["technique"], i) for t in doc.get("techniques", []) if t["level"] == "reproduction_suggestion" for i in t.get("ideas", [])]
    out += [f"- {tech}: {_esc(i['text'])}" + (f" (requer: {_esc(', '.join(i['requires']))})" if i.get("requires") else "")
            for tech, i in ideas] or ["- Nenhuma ideia registrada (sugestões não são afirmações sobre o vídeo)."]

    out += ["", "## Pendências", ""]
    pend = [p["description"] for p in doc.get("pending", [])] + open_questions(doc.get("techniques", []))
    pend += [f"decisão de revisão órfã: {o}" for o in doc.get("orphan_decisions", [])]
    out += [f"- {_esc(p)}" for p in pend] or ["- Nenhuma pendência registrada."]

    out += ["", "## Artefatos", ""]
    out += [f"- {f['frame_id']} @ {_ts(f['t_s'])}: " + (f"`{_esc(f['file'])}`" if f.get("file") else "(sem arquivo)") + f" sha256 `{f['sha256'][:12]}…`"
            for f in doc.get("frames", [])] or ["- Nenhum artefato."]

    out += ["", "## Curadoria", "", CUR_START, curation if curation is not None else DEFAULT_CURATION, CUR_END, ""]
    return "\n".join(out)


def _write_if_changed(path: Path, content: str) -> str:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    status = "updated" if path.exists() else "created"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ii_tmp_", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return status


def export_reference(doc: Dict[str, Any], staging_dir: Path) -> Dict[str, str]:
    assert_valid(doc)
    root = assert_staging(staging_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = safe_name(doc["reference"]["reference_id"])
    md_path, json_path = root / f"{name}.md", root / f"{name}.json"
    keys, curation = ({}, None)
    if md_path.exists():
        keys, curation = _split_existing(md_path.read_text(encoding="utf-8"))
    md = render(doc, curation, keys)
    return {"markdown": _write_if_changed(md_path, md),
            "json": _write_if_changed(json_path, json.dumps(json.loads(canonical_json(doc)), ensure_ascii=False, indent=2, sort_keys=True) + "\n"),
            "path": str(md_path)}
