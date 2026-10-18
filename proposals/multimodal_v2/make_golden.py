"""Gera regression_golden.json a partir do código ATUAL do Projeto-MVP (somente leitura).
Uso: PROJETO_MVP_DIR=/caminho/projeto-mvp python3 make_golden.py
Entradas são sintéticas; nenhum dado do catálogo é lido."""
import json, os, sys
from pathlib import Path

root = Path(os.environ["PROJETO_MVP_DIR"]).resolve()
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
from core.curation import evaluate_item_curation, suggest_editorial_category  # noqa: E402

# (caption, hashtags, known_defect)
INPUTS = [
    ("Como usar o ChatGPT para automatizar vendas", ["#ia"], False),
    ("Motion design com keyframes no After Effects", [], False),
    ("Tutorial de color grading no DaVinci", [], False),
    ("n8n workflow com webhook", [], False),
    ("Prospecção de leads no Google Maps", [], False),
    ("Copywriting e storytelling para viral", [], False),
    ("Moodboard de estética retrô", [], False),
    ("", [], False),
    ("bom dia", [], False),
    ("Edit do gol do Flamengo", [], False),
    ("Debate político sobre o governo", [], False),
    ("robotics demo", [], True),
    ("both teams won the game", [], True),
    ("how to make a cake at home", [], True),
    ("pizza do dev da esquina", [], True),
    ("copy of my receipt", [], True),
    ("motion design e keyframes, uma ia ajuda", [], True),
]
out = []
for cap, tags, defect in INPUTS:
    sug = suggest_editorial_category(cap, tags, "", "")
    out.append({
        "caption": cap, "hashtags": tags, "known_defect": defect,
        "curation": list(evaluate_item_curation(cap, tags, "", "")),
        "suggested_category": (sug or {}).get("suggested_category"),
    })
Path(__file__).with_name("regression_golden.json").write_text(
    json.dumps({"source_commit": os.environ.get("PROJETO_MVP_COMMIT", "unknown"), "cases": out}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(len(out), "casos")
