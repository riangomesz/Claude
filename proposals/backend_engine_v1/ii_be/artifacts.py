"""Registro de artefatos (Tarefa 10): mídia e saídas de ferramentas já produzidas (ffprobe, whisper, ffmpeg…).

- Caminho sempre RELATIVO a uma raiz gerenciada; validado com as mesmas regras de URI do contrato n8n do
  `ii_mm` (sem esquema, sem `..`, sem absoluto/unidade, sem ADS `:`, sem nome de dispositivo do Windows) e
  conferido depois de resolver links simbólicos (não escapa da raiz).
- Estado: verified (hash e tamanho conferem), partial (incompleto/menor que o esperado), corrupt (hash diverge),
  missing (arquivo ausente), temp (temporário), registered (sem conteúdo para conferir), superseded (versão antiga).
- Versão: mesmo (referência, tipo) com conteúdo novo vira versão nova; a anterior verificada vira `superseded`.
  Mesmo conteúdo de novo = idempotente (devolve o registro existente).
- Limpeza: SÓ artefatos `temp`, SÓ dentro de uma raiz com o marcador `.ii_be_store` criado por este módulo.
  Arquivos privados ou de mídia nunca são apagados automaticamente.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.n8n_contract import _bad_uri  # mesma regra de caminho do contrato n8n (reuso, não cópia)
from .errors import InvalidInput

ARTIFACT_KINDS = ("video", "audio", "ffprobe", "transcript_segments", "srt", "scenes_ffmpeg", "scene_candidates",
                  "frames_manifest", "frame_metrics", "observations", "metadata_snapshot", "evidence_package", "export_note", "temp")
MARKER = ".ii_be_store"
MAX_REL = 240
PARTIAL_SUFFIXES = (".part", ".partial", ".crdownload", ".tmp")


def safe_relpath(rel: str) -> str:
    if not isinstance(rel, str):
        raise InvalidInput("caminho de artefato ausente")
    norm = rel.replace("\\", "/")
    why = _bad_uri(norm)
    if why:
        raise InvalidInput(f"caminho de artefato recusado: {why}")
    parts = norm.split("/")  # componentes crus: PurePosixPath engoliria "//" e "./"
    if not parts or any(p in ("", ".") for p in parts) or len(norm) > MAX_REL:
        raise InvalidInput("caminho de artefato vazio, com componente vazio/'.' ou longo demais")
    return "/".join(parts)


@dataclass
class FileInfo:
    relpath: str
    exists: bool
    sha256: Optional[str]
    size_bytes: Optional[int]


class ArtifactStore:
    """Raiz gerenciada. `create` exige pasta nova (ou já marcada); nunca adota uma pasta alheia."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not (self.root / MARKER).is_file():
            raise InvalidInput(f"{self.root} não é uma raiz de artefatos gerenciada (falta {MARKER})")

    @classmethod
    def create(cls, root: Path) -> "ArtifactStore":
        root = Path(root)
        if root.exists() and any(root.iterdir()) and not (root / MARKER).is_file():
            raise InvalidInput(f"recusado: {root} já existe com conteúdo e não é gerenciada")
        root.mkdir(parents=True, exist_ok=True)
        (root / MARKER).write_text("raiz de artefatos do ii_be\n", encoding="utf-8")
        return cls(root)

    def path(self, rel: str) -> Path:
        rel = safe_relpath(rel)
        p = (self.root / rel)
        resolved = p.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise InvalidInput(f"caminho resolve para fora da raiz: {rel}") from None
        return p

    def inspect(self, rel: str) -> FileInfo:
        """Lê e calcula o hash FORA de transação (E/S de arquivo não segura o banco)."""
        p = self.path(rel)
        if not p.is_file():
            return FileInfo(safe_relpath(rel), False, None, None)
        h = hashlib.sha256()
        size = 0
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
        return FileInfo(safe_relpath(rel), True, h.hexdigest(), size)

    def write_bytes(self, rel: str, data: bytes) -> FileInfo:
        """Grava atomicamente (arquivo temporário + os.replace) dentro da raiz. Usado por fixtures e exportação."""
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".ii_tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        return self.inspect(rel)


def _artifact_id(reference_id: str, kind: str, version: int) -> str:
    return "art_" + hashlib.sha256(f"{reference_id}|{kind}|{version}".encode()).hexdigest()[:20]


def _state(info: FileInfo, expected_sha: Optional[str], expected_size: Optional[int], complete: bool, temp: bool) -> str:
    if temp:
        return "temp"
    if not info.exists:
        return "missing"
    if not complete or info.relpath.lower().endswith(PARTIAL_SUFFIXES) or (expected_size is not None and info.size_bytes < expected_size):
        return "partial"
    if expected_sha and expected_sha.lower() != info.sha256:
        return "corrupt"
    if expected_size is not None and info.size_bytes != expected_size:
        return "corrupt"
    return "verified"


def record(conn: sqlite3.Connection, reference_id: str, kind: str, info: FileInfo, origin: str, now_iso: str,
           expected_sha: Optional[str] = None, expected_size: Optional[int] = None, complete: bool = True,
           temp: bool = False, job_id: Optional[str] = None, depends_on: Iterable[str] = ()) -> dict:
    """Registra (dentro da transação do chamador). Devolve o registro, com `new=False` se já existia igual."""
    if not conn.in_transaction:
        raise RuntimeError("record exige transação aberta pelo chamador")
    if kind not in ARTIFACT_KINDS:
        raise InvalidInput(f"tipo de artefato desconhecido: {kind}")
    state = _state(info, expected_sha, expected_size, complete, temp)
    last = conn.execute("SELECT * FROM be_artifacts WHERE reference_id = ? AND kind = ? ORDER BY version DESC LIMIT 1",
                        (reference_id, kind)).fetchone()
    if last and last["sha256"] == info.sha256 and last["relpath"] == info.relpath and last["state"] == state:
        return dict(last, new=False)
    version = (last["version"] + 1) if last else 1
    aid = _artifact_id(reference_id, kind, version)
    conn.execute("INSERT INTO be_artifacts(artifact_id, reference_id, kind, version, relpath, sha256, size_bytes, expected_sha256, "
                 "expected_size, state, origin, job_id, created_at, verified_at, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (aid, reference_id, kind, version, info.relpath, info.sha256, info.size_bytes, expected_sha, expected_size, state,
                  origin, job_id, now_iso, now_iso if state == "verified" else None,
                  None if state == "verified" else f"estado {state} no registro"))
    if state == "verified":
        conn.execute("UPDATE be_artifacts SET state = 'superseded' WHERE reference_id = ? AND kind = ? AND version < ? AND state = 'verified'",
                     (reference_id, kind, version))
    for dep in depends_on:
        conn.execute("INSERT OR IGNORE INTO be_artifact_deps(artifact_id, depends_on) VALUES (?,?)", (aid, dep))
    row = conn.execute("SELECT * FROM be_artifacts WHERE artifact_id = ?", (aid,)).fetchone()
    return dict(row, new=True)


def current(conn: sqlite3.Connection, reference_id: str, kind: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM be_artifacts WHERE reference_id = ? AND kind = ? AND state = 'verified' "
                       "ORDER BY version DESC LIMIT 1", (reference_id, kind)).fetchone()
    return dict(row) if row else None


def latest(conn: sqlite3.Connection, reference_id: str, kind: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM be_artifacts WHERE reference_id = ? AND kind = ? ORDER BY version DESC LIMIT 1",
                       (reference_id, kind)).fetchone()
    return dict(row) if row else None


def verify(conn: sqlite3.Connection, store: ArtifactStore, artifact_id: str, now_iso: str) -> str:
    """Confere o arquivo de novo (hash fora da transação) e atualiza o estado: missing/corrupt/verified."""
    row = conn.execute("SELECT * FROM be_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
    if row is None:
        raise InvalidInput(f"artefato desconhecido: {artifact_id}")
    if row["state"] in ("temp", "superseded"):
        return row["state"]
    info = store.inspect(row["relpath"])
    if not info.exists:
        new_state, err = "missing", "arquivo ausente na verificação"
    elif row["sha256"] and info.sha256 != row["sha256"]:
        new_state, err = "corrupt", "conteúdo diverge do hash registrado"
    elif row["state"] == "partial" and (row["expected_size"] is None or info.size_bytes < row["expected_size"]):
        new_state, err = "partial", "ainda incompleto"
    else:
        new_state, err = ("verified", None) if row["sha256"] else ("registered", "sem hash registrado")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE be_artifacts SET state = ?, error = ?, verified_at = ? WHERE artifact_id = ?",
                     (new_state, err, now_iso, artifact_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return new_state


def cleanup_temp(conn: sqlite3.Connection, store: ArtifactStore, now_iso: str) -> List[str]:
    """Apaga SÓ arquivos de artefatos `temp` dentro da raiz gerenciada; o registro fica (estado missing)."""
    removed = []
    for row in conn.execute("SELECT artifact_id, relpath FROM be_artifacts WHERE state = 'temp' ORDER BY artifact_id").fetchall():
        p = store.path(row["relpath"])
        if p.is_file() and not p.is_symlink():
            p.unlink()
            removed.append(row["relpath"])
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE be_artifacts SET state = 'missing', error = 'removido pela limpeza de temporários', verified_at = ? "
                         "WHERE artifact_id = ?", (now_iso, row["artifact_id"]))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return removed


def media_state(conn: sqlite3.Connection, reference_id: str) -> str:
    """Estado de aquisição derivado dos artefatos (sem coluna duplicada): none|partial|corrupt|missing|available."""
    row = latest(conn, reference_id, "video")
    if row is None:
        return "none"
    if current(conn, reference_id, "video"):
        return "available"
    return {"partial": "partial", "corrupt": "corrupt", "missing": "missing"}.get(row["state"], row["state"])
