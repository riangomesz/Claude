"""Validador de RECEBIMENTO da Release Candidate (roda ANTES de qualquer código do pacote).

Uso (na pasta multimodal_v2 do pacote recebido):
    python handoff/verificar_recebimento.py [--manifest-sha256 <hex publicado no handoff>] [--json]

Garantias:
- Só biblioteca padrão; não importa `ii_mm` nem executa nada do pacote; não grava nenhum arquivo.
- O SQLite é sondado só em memória (`:memory:`).

Detecta: manifesto ilegível ou de versão desconhecida; manifesto diferente do hash publicado; arquivo
ausente; arquivo modificado; arquivo extra nas pastas gerenciadas; caminho perigoso (absoluto, `..`,
unidade, `:`, nome reservado do Windows, colisão de maiúsculas, caminho longo); Python ou SQLite abaixo do
mínimo; módulo obrigatório da stdlib ausente.

Códigos de saída: 0 = ok · 1 = integridade · 2 = ambiente (dependência) · 3 = uso/manifesto ilegível.
Atenção: um validador adulterado pode mentir. Confira o hash do manifesto com o valor publicado no
documento de handoff (fora do pacote) usando --manifest-sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path, PurePosixPath

SUPPORTED_MANIFESTS = {"ii.handoff_manifest.v2"}
REQUIRED_STDLIB = ("sqlite3", "json", "hashlib", "unittest", "tempfile", "zipfile", "dataclasses", "urllib.parse", "importlib")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
MAX_REL_PATH = 200  # folga para a pasta de instalação dentro do limite clássico de 260 caracteres
IGNORED_EXTRA = ("__pycache__", ".pyc")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _version_tuple(text: str):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def path_problems(rel: str):
    p = []
    if not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
        p.append("caminho absoluto ou com unidade")
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if ".." in parts:
        p.append("contém '..'")
    for part in parts:
        if re.search(r'[<>:"|?*\x00-\x1f]', part):
            p.append(f"caractere inválido no Windows em '{part}'")
        if part.split(".")[0].upper() in WINDOWS_RESERVED:
            p.append(f"nome reservado do Windows: '{part}'")
        if part.endswith((" ", ".")) and part not in (".", ".."):
            p.append(f"componente termina em espaço/ponto: '{part}'")
    if len(rel) > MAX_REL_PATH:
        p.append(f"caminho relativo com {len(rel)} caracteres (> {MAX_REL_PATH})")
    return p


def check(proposals_root: Path, manifest_sha256: str = None) -> dict:
    report = {"integrity": [], "environment": [], "warnings": [], "files_checked": 0, "rc_id": None, "manifest_sha256": None}
    man_path = proposals_root / "multimodal_v2" / "handoff" / "MANIFESTO_PACOTE.json"
    try:
        raw = man_path.read_bytes()
        man = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        report["fatal"] = f"manifesto ilegível em {man_path}: {exc.__class__.__name__}"
        return report
    report["manifest_sha256"] = content_hash(raw)
    if manifest_sha256 and manifest_sha256.lower() != report["manifest_sha256"]:
        report["integrity"].append("manifesto difere do hash publicado no handoff (possível adulteração ou versão errada)")
    if not isinstance(man, dict) or man.get("schema_version") not in SUPPORTED_MANIFESTS:
        report["fatal"] = f"versão de manifesto não suportada: {man.get('schema_version') if isinstance(man, dict) else type(man).__name__}"
        return report
    report["rc_id"] = man.get("rc_id")
    if not re.fullmatch(r"ii_mm-\d+\.\d+\.\d+-rc\d+", str(man.get("rc_id", ""))):
        report["integrity"].append(f"rc_id inválido: {man.get('rc_id')!r}")

    req = man.get("requirements", {})
    if sys.version_info[:3] < _version_tuple(req.get("python_min", "3.11")):
        report["environment"].append(f"Python {sys.version.split()[0]} < mínimo {req.get('python_min')}")
    for mod in REQUIRED_STDLIB:
        if importlib.util.find_spec(mod.split(".")[0]) is None:
            report["environment"].append(f"módulo obrigatório ausente: {mod}")
    if _version_tuple(sqlite3.sqlite_version) < _version_tuple(req.get("sqlite_min", "3.24.0")):
        report["environment"].append(f"SQLite {sqlite3.sqlite_version} < mínimo {req.get('sqlite_min')}")
    else:
        try:  # UPSERT e comparação de tuplas, só em memória
            c = sqlite3.connect(":memory:")
            try:
                c.execute("CREATE TABLE t (a INTEGER PRIMARY KEY, b INTEGER)")
                c.execute("INSERT INTO t VALUES (1, 1) ON CONFLICT(a) DO UPDATE SET b = excluded.b")
                c.execute("SELECT * FROM t WHERE (a, b) > (0, 0)").fetchall()
            finally:
                c.close()
        except sqlite3.Error as exc:
            report["environment"].append(f"SQLite sem recurso necessário: {exc}")

    files = man.get("files")
    if not isinstance(files, list) or not files:
        report["fatal"] = "manifesto sem lista de arquivos"
        return report
    seen_lower = {}
    listed = set()
    for entry in files:
        rel = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(rel, str):
            report["integrity"].append(f"entrada de arquivo inválida: {entry!r}"[:120])
            continue
        for prob in path_problems(rel):
            report["integrity"].append(f"{rel}: {prob}")
        key = rel.lower()
        if key in seen_lower:
            report["integrity"].append(f"colisão de maiúsculas/minúsculas no NTFS: {rel} × {seen_lower[key]}")
        seen_lower[key] = rel
        listed.add(rel)
        target = proposals_root / rel
        try:
            target.resolve().relative_to(proposals_root.resolve())
        except ValueError:
            report["integrity"].append(f"{rel}: resolve para fora do pacote")
            continue
        if not target.is_file():
            report["integrity"].append(f"ausente: {rel}")
            continue
        if content_hash(target.read_bytes()) != entry.get("sha256_lf"):
            report["integrity"].append(f"modificado: {rel}")
        report["files_checked"] += 1

    for d in man.get("managed_dirs", []):
        base = proposals_root / d
        if not base.is_dir():
            report["integrity"].append(f"pasta gerenciada ausente: {d}")
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(proposals_root).as_posix()
            if rel in listed or f.name == "MANIFESTO_PACOTE.json":
                continue
            if any(x in rel for x in IGNORED_EXTRA):
                report["warnings"].append(f"cache de bytecode presente (inofensivo): {rel}")
            else:
                report["integrity"].append(f"arquivo extra não listado: {rel}")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Valida a Release Candidate recebida antes de executá-la.")
    ap.add_argument("--root", help="pasta 'proposals' do pacote (padrão: deduzida da localização deste script)")
    ap.add_argument("--manifest-sha256", help="hash do manifesto publicado no documento de handoff")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(__file__).resolve().parents[2]
    rep = check(root, a.manifest_sha256)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"RC: {rep.get('rc_id')} | manifesto sha256(LF): {rep.get('manifest_sha256')} | arquivos conferidos: {rep['files_checked']}")
        for k in ("fatal", ):
            if rep.get(k):
                print(f"FATAL: {rep[k]}")
        for p in rep["integrity"]:
            print(f"INTEGRIDADE: {p}")
        for p in rep["environment"]:
            print(f"AMBIENTE: {p}")
        for p in rep["warnings"]:
            print(f"aviso: {p}")
    if rep.get("fatal"):
        return 3
    if rep["integrity"]:
        return 1
    if rep["environment"]:
        return 2
    if not a.json:
        print("OK: pacote íntegro e ambiente compatível")
    return 0


if __name__ == "__main__":
    sys.exit(main())
