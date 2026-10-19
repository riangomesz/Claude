"""Fluxo de avaliação humana (Missão Suprema 03, Etapa 12). Nada aqui produz resultado sem rótulo humano.

1. `select_sample`: amostra estratificada e reproduzível (30 a 50 itens), a partir do relatório do modo sombra.
2. `export_labeling_sheet`: planilha CEGA por padrão (não mostra as sugestões dos classificadores, para não
   ancorar o revisor); uma coluna por categoria (marcar 1 ou 0) + observações.
3. `load_labels`: valida a planilha devolvida (categoria desconhecida, valor inválido, duplicata, revisor ausente).
4. `agreement_report`: compara cada classificador com o rótulo humano, por categoria, em CONTAGENS
   (concorda/discorda, falso positivo/negativo relativo ao humano). A taxa só aparece com n ≥ 30 e sempre
   acompanhada do tamanho da amostra; abaixo disso o relatório se recusa a dar taxa.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .evidence_rules import CATEGORIES
from .shadow import _cell

MIN_SAMPLE, MAX_SAMPLE = 30, 50
VALID_MARKS = {"1": True, "0": False, "": None}


class LabelError(ValueError):
    pass


def select_sample(items: Sequence[Dict[str, Any]], n: int = 40, seed: int = 20261019, stratum_key: str = "kind") -> Dict[str, Any]:
    """Amostra estratificada por `stratum_key` (padrão: tipo de divergência do modo sombra), proporcional e reproduzível."""
    if not MIN_SAMPLE <= n <= MAX_SAMPLE:
        raise ValueError(f"n deve estar entre {MIN_SAMPLE} e {MAX_SAMPLE}")
    pool = [i for i in items if i.get("status", "compared") == "compared" and i.get("item_id")]
    rnd = random.Random(seed)
    strata: Dict[str, List[Dict[str, Any]]] = {}
    for it in sorted(pool, key=lambda x: str(x["item_id"])):
        strata.setdefault(str(it.get(stratum_key)), []).append(it)
    if len(pool) <= n:
        chosen = list(pool)
    else:
        chosen = []
        for key in sorted(strata):  # cota proporcional com pelo menos 1 por estrato
            quota = max(1, round(n * len(strata[key]) / len(pool)))
            chosen += rnd.sample(strata[key], min(quota, len(strata[key])))
        rnd.shuffle(chosen)
        chosen = sorted(chosen[:n], key=lambda x: str(x["item_id"]))
    warnings = [] if len(chosen) >= MIN_SAMPLE else [f"só {len(chosen)} itens disponíveis (< {MIN_SAMPLE}): concordância não será calculada como taxa"]
    return {"seed": seed, "requested": n, "selected": [i["item_id"] for i in chosen], "items": chosen,
            "strata": {k: len(v) for k, v in strata.items()}, "warnings": warnings}


def export_labeling_sheet(sample: Dict[str, Any], path: Path, rows: Dict[str, Dict[str, Any]], blind: bool = True) -> int:
    """`rows`: item_id → linha legada (para mostrar legenda e URL ao revisor). Sem sugestões quando `blind`."""
    cols = ["item_id", "url", "legenda"] + ([] if blind else ["sugestao_atual", "sugestao_nova"]) + list(CATEGORIES) + ["observacoes", "revisor", "data"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for it in sample["items"]:
            r = rows.get(it["item_id"], {})
            line = [it["item_id"], r.get("url"), (r.get("caption") or "")[:300]]
            if not blind:
                line += [it.get("legacy", {}).get("label"), "; ".join(sorted(it.get("new", {})))]
            w.writerow([_cell(x) for x in line] + [""] * len(CATEGORIES) + ["", "", ""])
    return len(sample["items"])


def load_labels(path: Path) -> Dict[str, Set[str]]:
    """Planilha preenchida → item_id → categorias marcadas com 1. Erros de preenchimento viram LabelError."""
    errors: List[str] = []
    labels: Dict[str, Set[str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("item_id", "revisor", *CATEGORIES) if c not in (reader.fieldnames or [])]
        if missing:
            raise LabelError(f"colunas ausentes: {missing}")
        for n, row in enumerate(reader, start=2):
            item = (row.get("item_id") or "").lstrip("'").strip()
            if not item:
                errors.append(f"linha {n}: item_id vazio")
                continue
            if item in labels:
                errors.append(f"linha {n}: item {item} rotulado duas vezes")
                continue
            marks = {c: (row.get(c) or "").strip() for c in CATEGORIES}
            bad = {c: v for c, v in marks.items() if v not in VALID_MARKS}
            if bad:
                errors.append(f"linha {n}: valores inválidos {bad} (use 1, 0 ou vazio)")
                continue
            if all(v == "" for v in marks.values()):
                continue  # item não revisado: fica fora da avaliação
            if not (row.get("revisor") or "").strip():
                errors.append(f"linha {n}: revisor ausente")
                continue
            labels[item] = {c for c, v in marks.items() if v == "1"}
    if errors:
        raise LabelError("; ".join(errors[:20]))
    return labels


def agreement_report(labels: Dict[str, Set[str]], predictions: Dict[str, Dict[str, Set[str]]]) -> Dict[str, Any]:
    """`predictions`: nome_do_classificador → item_id → categorias previstas. Só itens com rótulo humano entram."""
    n = len(labels)
    out = {"n_labeled": n, "per_classifier": {}, "note": "Contagens relativas ao rótulo humano; não é verdade absoluta."}
    for name, pred in predictions.items():
        per_cat = {}
        for cat in CATEGORIES:
            tp = sum(1 for i, h in labels.items() if cat in h and cat in pred.get(i, set()))
            fp = sum(1 for i, h in labels.items() if cat not in h and cat in pred.get(i, set()))
            fn = sum(1 for i, h in labels.items() if cat in h and cat not in pred.get(i, set()))
            tn = n - tp - fp - fn
            entry = {"concorda_presente": tp, "falso_positivo": fp, "falso_negativo": fn, "concorda_ausente": tn}
            if n >= MIN_SAMPLE:
                entry["taxa_concordancia"] = round((tp + tn) / n, 3)
            per_cat[cat] = entry
        exact = sum(1 for i, h in labels.items() if pred.get(i, set()) == h)
        out["per_classifier"][name] = {"por_categoria": per_cat, "itens_identicos_ao_humano": exact,
                                       "itens_com_algum_erro": n - exact}
    if n < MIN_SAMPLE:
        out["warning"] = f"amostra rotulada com {n} itens (< {MIN_SAMPLE}): só contagens, sem taxa"
    return out


def predictions_from_shadow(report: Dict[str, Any]) -> Dict[str, Dict[str, Set[str]]]:
    """Extrai as previsões dos dois classificadores do relatório do modo sombra (categorias v2)."""
    legacy, new = {}, {}
    for it in report.get("items", []):
        if it.get("status") != "compared":
            continue
        mapped = it["legacy"].get("mapped")
        legacy[it["item_id"]] = {mapped} if mapped else set()
        new[it["item_id"]] = set(it.get("new", {}))
    return {"atual": legacy, "novo": new}
