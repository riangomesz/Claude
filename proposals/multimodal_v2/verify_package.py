"""Confere um pacote_analise_2 recebido contra o próprio manifesto, antes de qualquer análise.

Uso: python3 verify_package.py CAMINHO/pacote_analise_2
Somente leitura. Sai com código 0 se o pacote está íntegro e completo, 1 caso contrário.
Não lê o vídeo nem abre imagens: só nomes, tamanhos e SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import List

REQUIRED_JSON = ("manifesto_pacote.json", "perguntas_de_verificacao.json",
                 "segmentos_transcricao.json", "cortes_detectados.json")
MAX_FRAMES = 12


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(pkg: Path) -> List[str]:
    problems: List[str] = []
    for name in REQUIRED_JSON:
        if not (pkg / name).is_file():
            problems.append(f"ausente: {name}")
    if problems and "ausente: manifesto_pacote.json" in problems:
        return problems
    try:
        manifest = json.loads((pkg / "manifesto_pacote.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return problems + [f"manifesto_pacote.json ilegível: {exc.__class__.__name__}"]
    if not isinstance(manifest, dict) or not isinstance(manifest.get("frames", []), list):
        return problems + ["manifesto_pacote.json fora do formato esperado (objeto com lista 'frames')"]
    frames = manifest.get("frames", [])
    if not frames:
        problems.append("manifesto sem frames")
    if len(frames) > MAX_FRAMES:
        problems.append(f"mais de {MAX_FRAMES} frames no manifesto")
    root = pkg.resolve()
    listed = set()
    for fr in frames:
        rel = fr.get("file") if isinstance(fr, dict) else None
        if not isinstance(rel, str) or not rel.strip():
            pid = fr.get("pacote_id") if isinstance(fr, dict) else None
            problems.append(f"{pid}: entrada de frame sem campo 'file'")
            continue
        target = (pkg / rel).resolve()
        if target in listed:
            problems.append(f"{fr.get('pacote_id')}: frame listado em duplicidade: {rel}")
            continue
        if root not in target.parents:
            problems.append(f"{fr.get('pacote_id')}: caminho fora do pacote: {rel}")
            continue
        listed.add(target)
        if not target.is_file():
            problems.append(f"{fr.get('pacote_id')}: frame ausente: {rel}")
        elif _sha256(target) != fr.get("sha256"):
            problems.append(f"{fr.get('pacote_id')}: SHA-256 diverge do manifesto: {rel}")
    frames_dir = pkg / "frames"
    if frames_dir.is_dir():
        for extra in sorted(frames_dir.iterdir()):
            if extra.is_file() and extra.resolve() not in listed:
                problems.append(f"arquivo não listado no manifesto: frames/{extra.name}")
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    issues = verify(Path(sys.argv[1]))
    print("\n".join(issues) if issues else "pacote íntegro")
    sys.exit(1 if issues else 0)
