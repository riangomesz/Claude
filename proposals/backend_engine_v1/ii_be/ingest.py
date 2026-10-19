"""Ingestão unificada (Tarefa 03).

Contrato `ii.be.ingest.v1` (fechado: chave desconhecida é recusada):

    {"schema_version": "ii.be.ingest.v1", "source_kind": "instagram|youtube|meta_export|manifest|local_file|manual",
     "platform": str?, "url": str?, "native_id": str?, "source_ref": str?, "observed_at": ISO-8601?,
     "metadata": {caption, title, author_handle, author_name, hashtags[], published_at, duration_s, language,
                  media_type, view_count, like_count}?,
     "media": {"relpath": str, "sha256": str?, "size_bytes": int?, "complete": bool?}?,
     "acquisition_hint": "metadata_only|media_pending|media_available|not_authorized"?}

Regras:
- Nenhum campo ausente é inventado: o que não veio fica `None`/fora do histórico.
- Sem URL, sem (plataforma + id) e sem mídia local, a referência é recusada (sem identidade confiável).
- Ingestão é idempotente: o mesmo registro (mesma origem + mesmo conteúdo) não cria nada de novo.
- Nenhuma coleta ativa: os adaptadores leem dados JÁ obtidos de forma autorizada (exportação da Meta,
  manifestos, arquivos locais, entrada manual). Nada de scraping nem acesso a conta.
- Texto externo (legenda, título) é dado, nunca instrução; fica limitado em tamanho.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm._matcher import normalize
from ii_mm.contract import canonical_json
from ii_mm.dedup import IdentityError, parse_reference
from . import artifacts as A
from .clock import iso
from .db import tx
from .errors import InvalidInput
from .events import emit
from .identity import META_FIELDS, clean_url, current_metadata, local_native_id, record_metadata, register_reference, resolve_key

INGEST_SCHEMA = "ii.be.ingest.v1"
SOURCE_KINDS = ("instagram", "youtube", "meta_export", "manifest", "local_file", "manual")
ACQUISITION_HINTS = ("metadata_only", "media_pending", "media_available", "not_authorized")
_KEYS = {"schema_version", "source_kind", "platform", "url", "native_id", "source_ref", "observed_at", "metadata", "media",
         "acquisition_hint"}
_MEDIA_KEYS = {"relpath", "sha256", "size_bytes", "complete"}
MAX_TEXT = 10_000
MAX_SHORT = 512
MAX_HASHTAGS = 100
TERM_STOP = {"de", "da", "do", "das", "dos", "que", "com", "para", "uma", "um", "the", "and", "for", "you", "this", "isso",
             "essa", "esse", "aqui", "nao", "mais", "como", "por", "sem", "seu", "sua"}


def _is_iso(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_record(rec: Any) -> List[str]:
    p: List[str] = []
    if not isinstance(rec, dict):
        return ["registro deve ser objeto"]
    unknown = set(rec) - _KEYS
    if unknown:
        p.append(f"chaves desconhecidas: {sorted(unknown)}")
    if rec.get("schema_version") != INGEST_SCHEMA:
        p.append(f"schema_version deve ser {INGEST_SCHEMA}")
    if rec.get("source_kind") not in SOURCE_KINDS:
        p.append(f"source_kind inválido: {rec.get('source_kind')!r}")
    for k in ("platform", "url", "native_id", "source_ref"):
        v = rec.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > MAX_SHORT or any(ord(c) < 32 for c in v)):
            p.append(f"{k} inválido")
    if rec.get("observed_at") is not None and not _is_iso(rec["observed_at"]):
        p.append("observed_at não é ISO-8601")
    if rec.get("acquisition_hint") is not None and rec["acquisition_hint"] not in ACQUISITION_HINTS:
        p.append("acquisition_hint inválido")
    meta = rec.get("metadata")
    if meta is not None:
        if not isinstance(meta, dict):
            p.append("metadata deve ser objeto")
        else:
            extra = set(meta) - set(META_FIELDS)
            if extra:
                p.append(f"metadata com campos desconhecidos: {sorted(extra)}")
            for k in ("caption", "title"):
                if meta.get(k) is not None and (not isinstance(meta[k], str) or len(meta[k]) > MAX_TEXT):
                    p.append(f"metadata.{k} inválido ou maior que {MAX_TEXT} caracteres")
            for k in ("author_handle", "author_name", "language", "media_type", "published_at"):
                if meta.get(k) is not None and (not isinstance(meta[k], str) or len(meta[k]) > MAX_SHORT):
                    p.append(f"metadata.{k} inválido")
            if meta.get("published_at") is not None and not _is_iso(meta["published_at"]):
                p.append("metadata.published_at não é ISO-8601")
            tags = meta.get("hashtags")
            if tags is not None and (not isinstance(tags, list) or len(tags) > MAX_HASHTAGS
                                     or not all(isinstance(t, str) and len(t) <= 100 for t in tags)):
                p.append("metadata.hashtags inválido")
            d = meta.get("duration_s")
            if d is not None and (isinstance(d, bool) or not isinstance(d, (int, float)) or not 0 < d < 86400):
                p.append("metadata.duration_s fora do intervalo")
            for k in ("view_count", "like_count"):
                v = meta.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                    p.append(f"metadata.{k} inválido")
    media = rec.get("media")
    if media is not None:
        if not isinstance(media, dict) or set(media) - _MEDIA_KEYS or not isinstance(media.get("relpath"), str):
            p.append("media inválida (relpath obrigatório; chaves: relpath, sha256, size_bytes, complete)")
        else:
            try:
                A.safe_relpath(media["relpath"])
            except InvalidInput as exc:
                p.append(str(exc))
            sha = media.get("sha256")
            if sha is not None and not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha.lower())):
                p.append("media.sha256 inválido")
            sz = media.get("size_bytes")
            if sz is not None and (isinstance(sz, bool) or not isinstance(sz, int) or sz < 0):
                p.append("media.size_bytes inválido")
    return p


# --------------------------------------------------------------------------- adaptadores (dados já obtidos)
def record_from_url(url: str, source_kind: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                    observed_at: Optional[str] = None, source_ref: Optional[str] = None) -> Dict[str, Any]:
    try:
        platform, _ = parse_reference(url)
    except IdentityError as exc:
        raise InvalidInput(str(exc)) from None
    kind = source_kind or (platform if platform in ("instagram", "youtube") else "manual")
    rec = {"schema_version": INGEST_SCHEMA, "source_kind": kind, "url": url, "source_ref": source_ref or clean_url(url)}
    if metadata:
        rec["metadata"] = metadata
    if observed_at:
        rec["observed_at"] = observed_at
    return rec


def _ts_to_iso(ts: Any) -> Optional[str]:
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def records_from_meta_export(payload: Any, export_name: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Exportação de dados da Meta (formato JSON da conta, obtido pelo próprio usuário).

    Lê as listas conhecidas (`saved_saved_media`, `likes_media_likes`) e qualquer item com `string_map_data`
    ou `string_list_data` contendo `href`. Item sem URL reconhecível vira erro reportado, nunca exceção.
    `title` desses arquivos é o nome de usuário do autor (metadado declarado, não verificado)."""
    errors: List[str] = []
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return [], ["exportação ilegível (JSON inválido)"]
    sections: List[Tuple[str, list]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list):
                sections.append((key, value))
    elif isinstance(payload, list):
        sections.append(("itens", payload))
    else:
        return [], ["exportação sem listas reconhecíveis"]
    records = []
    for section, items in sections:
        for i, item in enumerate(items[:50_000]):
            if not isinstance(item, dict):
                errors.append(f"{section}[{i}]: item não é objeto")
                continue
            entries = []
            smd = item.get("string_map_data")
            if isinstance(smd, dict):
                entries += [v for v in smd.values() if isinstance(v, dict)]
            sld = item.get("string_list_data")
            if isinstance(sld, list):
                entries += [v for v in sld if isinstance(v, dict)]
            href = next((e.get("href") for e in entries if isinstance(e.get("href"), str)), None)
            ts = next((e.get("timestamp") for e in entries if e.get("timestamp") is not None), None)
            if not href:
                errors.append(f"{section}[{i}]: sem URL")
                continue
            try:
                parse_reference(href)
            except IdentityError as exc:
                errors.append(f"{section}[{i}]: {exc}")
                continue
            meta = {}
            if isinstance(item.get("title"), str) and item["title"].strip():
                meta["author_handle"] = item["title"].strip()[:MAX_SHORT]
            rec = {"schema_version": INGEST_SCHEMA, "source_kind": "meta_export", "url": href,
                   "source_ref": f"{export_name}#{section}[{i}]", "acquisition_hint": "metadata_only"}
            obs = _ts_to_iso(ts)
            if obs:
                rec["observed_at"] = obs
            if meta:
                rec["metadata"] = meta
            records.append(rec)
    return records, errors


def record_from_manifest(manifest: Any, source_ref: str, url: Optional[str] = None, platform: Optional[str] = None) -> Dict[str, Any]:
    """Manifesto de pacote de evidências (`ii.evidence_package.v1` / `ii.coverage.manifest.v1`).

    O manifesto informa o hash da mídia, mas não o arquivo: a mídia fica `media_pending` até ser registrada."""
    if not isinstance(manifest, dict):
        raise InvalidInput("manifesto deve ser objeto")
    sha = manifest.get("video_sha256") or (manifest.get("video") or {}).get("sha256")
    url = url or manifest.get("url") or (manifest.get("video") or {}).get("url")
    rec: Dict[str, Any] = {"schema_version": INGEST_SCHEMA, "source_kind": "manifest", "source_ref": source_ref,
                           "acquisition_hint": "media_pending"}
    if url:
        rec["url"] = url
    elif sha:
        rec["platform"], rec["native_id"] = (platform or "local"), local_native_id(str(sha).lower())
    return rec


def record_from_local_file(relpath: str, url: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                           expected_sha256: Optional[str] = None, complete: bool = True) -> Dict[str, Any]:
    """Arquivo já adquirido, dentro da raiz gerenciada. Sem URL, a identidade vem do conteúdo (plataforma `local`)."""
    rec: Dict[str, Any] = {"schema_version": INGEST_SCHEMA, "source_kind": "local_file", "source_ref": relpath,
                           "media": {"relpath": relpath, "complete": complete}, "acquisition_hint": "media_available"}
    if expected_sha256:
        rec["media"]["sha256"] = expected_sha256
    if url:
        rec["url"] = url
    if metadata:
        rec["metadata"] = metadata
    return rec


def manual_record(platform: Optional[str] = None, native_id: Optional[str] = None, url: Optional[str] = None,
                  metadata: Optional[Dict[str, Any]] = None, source_ref: str = "manual") -> Dict[str, Any]:
    rec: Dict[str, Any] = {"schema_version": INGEST_SCHEMA, "source_kind": "manual", "source_ref": source_ref}
    for k, v in (("platform", platform), ("native_id", native_id), ("url", url)):
        if v:
            rec[k] = v
    if metadata:
        rec["metadata"] = metadata
    return rec


# --------------------------------------------------------------------------- serviço
@dataclass
class IngestResult:
    reference_id: str
    canonical_key: str
    created: bool
    duplicate: bool
    metadata_changed: List[str] = field(default_factory=list)
    media_state: str = "none"
    artifact_id: Optional[str] = None
    alias_conflicts: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)


def terms_for(meta: Dict[str, Any]) -> set:
    texts = [meta.get(k) or "" for k in ("caption", "title")] + list(meta.get("hashtags") or [])
    terms = {w for t in texts for w in normalize(str(t)).split() if len(w) >= 3 and w not in TERM_STOP}
    if meta.get("author_handle"):
        terms.add("author:" + normalize(meta["author_handle"]).replace(" ", ""))
    return terms


class IngestService:
    def __init__(self, conn: sqlite3.Connection, clock, store: Optional[A.ArtifactStore] = None):
        self.conn, self.clock, self.store = conn, clock, store

    def ingest(self, rec: Dict[str, Any]) -> IngestResult:
        problems = validate_record(rec)
        if problems:
            raise InvalidInput("; ".join(problems))
        media = rec.get("media")
        info = None
        if media:
            if self.store is None:
                raise InvalidInput("mídia local exige uma raiz de artefatos gerenciada")
            info = self.store.inspect(media["relpath"])  # E/S fora da transação
        try:
            if rec.get("url") or (rec.get("platform") and rec.get("native_id")):
                platform, native, key = resolve_key(rec.get("platform"), rec.get("url"), rec.get("native_id"))
            elif info and info.exists:
                platform, native = "local", local_native_id(info.sha256)
                _, _, key = resolve_key(platform, None, native)
            else:
                raise IdentityError("sem identidade confiável: informe URL, plataforma + id nativo ou um arquivo existente")
        except IdentityError as exc:
            raise InvalidInput(str(exc)) from None
        payload_sha = hashlib.sha256(canonical_json(rec).encode("utf-8")).hexdigest()
        dedup_key = hashlib.sha256(f"{rec['source_kind']}|{rec.get('source_ref') or ''}|{payload_sha}".encode()).hexdigest()
        now = self.clock.now()
        now_iso = iso(now)
        with tx(self.conn) as c:
            reg = register_reference(c, platform, native, rec.get("url"), now_iso, seen_urls=[rec["url"]] if rec.get("url") else [])
            cur = c.execute("INSERT OR IGNORE INTO be_sources(reference_id, source_kind, source_ref, observed_at, received_at, payload_sha256, "
                            "acquisition_hint, dedup_key) VALUES (?,?,?,?,?,?,?,?)",
                            (reg.reference_id, rec["source_kind"], rec.get("source_ref"), rec.get("observed_at"), now_iso, payload_sha,
                             rec.get("acquisition_hint"), dedup_key))
            if cur.rowcount == 0:
                return IngestResult(reg.reference_id, reg.canonical_key, False, True, media_state=A.media_state(c, reg.reference_id),
                                    alias_conflicts=reg.alias_conflicts)
            source_id = cur.lastrowid
            changed = record_metadata(c, reg.reference_id, source_id, rec.get("metadata") or {}, rec.get("observed_at"), now_iso)
            if changed or reg.created:
                terms = terms_for(current_metadata(c, reg.reference_id))
                c.execute("DELETE FROM be_terms WHERE reference_id = ?", (reg.reference_id,))  # termos refletem o valor corrente
                c.executemany("INSERT OR IGNORE INTO be_terms(term, reference_id) VALUES (?,?)", [(t, reg.reference_id) for t in sorted(terms)])
            result = IngestResult(reg.reference_id, reg.canonical_key, reg.created, False, changed, alias_conflicts=reg.alias_conflicts)
            if reg.created or changed:
                e = emit(c, "reference.ingested", reg.reference_id,
                         {"reference_id": reg.reference_id, "canonical_key": reg.canonical_key, "created": reg.created,
                          "metadata_changed": changed, "source_kind": rec["source_kind"]}, now, dedup_key=f"source|{source_id}")
                result.events += [e] if e else []
            if info is not None:
                art = A.record(c, reg.reference_id, "video", info, origin=f"ingest:{rec['source_kind']}", now_iso=now_iso,
                               expected_sha=media.get("sha256"), expected_size=media.get("size_bytes"),
                               complete=media.get("complete", True))
                result.artifact_id = art["artifact_id"]
                if art["state"] == "verified":
                    e = emit(c, "media.available", reg.reference_id,
                             {"reference_id": reg.reference_id, "artifact_id": art["artifact_id"], "sha256": art["sha256"],
                              "shared_with": [r[0] for r in c.execute(
                                  "SELECT DISTINCT reference_id FROM be_artifacts WHERE sha256 = ? AND kind = 'video' AND reference_id <> ? "
                                  "AND state IN ('verified','superseded') ORDER BY reference_id", (art["sha256"], reg.reference_id))]},
                             now, dedup_key=f"media|{art['artifact_id']}")
                    result.events += [e] if e else []
            result.media_state = A.media_state(c, reg.reference_id)
        return result
