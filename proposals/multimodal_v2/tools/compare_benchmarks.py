"""Compara dois resultados de benchmark (mesma metodologia). Uso: python3 tools/compare_benchmarks.py A.json B.json
Ressalva impressa sempre: execuções diferentes têm ruído; só compare ambientes iguais."""
import json
import sys

METRICS = [
    ("classify_per_doc_ms", "Classificação (ms/doc)"),
    ("insert_per_doc_ms", "Inserção (ms/doc)"),
    ("query_first_page.median_ms", "Primeira página (ms)"),
    ("query_deep_page_cursor.median_ms", "Página do meio, cursor (ms)"),
    ("query_deep_page_offset.median_ms", "Página do meio, OFFSET (ms)"),
    ("query_category.median_ms", "Filtro categoria (ms)"),
    ("query_subject.median_ms", "Filtro assunto (ms)"),
    ("query_tool_visual.median_ms", "Filtro sem resultado (ms)"),
    ("scan_paginated.ms", "Varredura paginada (ms)"),
    ("scan_paginated.peak_python_mb", "Varredura paginada, pico (MB)"),
    ("duplicates_created", "Duplicatas após reenvios"),
    ("resume.repeated_executions", "Retomada: execuções repetidas"),
]


def get(d, path):
    for k in path.split("."):
        d = d[k]
    return d


def main(a_path, b_path):
    a, b = json.load(open(a_path, encoding="utf-8")), json.load(open(b_path, encoding="utf-8"))
    same = {k: a["environment"].get(k) == b["environment"].get(k) for k in ("python", "sqlite", "cpu_count", "machine")}
    print("Ambiente igual:", same)
    print("Ressalva: execuções diferentes; diferenças pequenas (< ~20%) estão dentro do ruído típico deste ambiente.\n")
    for ra in a["runs"]:
        rb = next((r for r in b["runs"] if r["records"] == ra["records"]), None)
        if not rb:
            continue
        print(f"## {ra['records']} registros")
        print("| Métrica | A | B |\n|---|---|---|")
        for path, label in METRICS:
            print(f"| {label} | {get(ra, path)} | {get(rb, path)} |")
        print()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
