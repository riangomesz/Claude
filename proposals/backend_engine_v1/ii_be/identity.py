"""Identidade e deduplicação (Tarefa 04), sobre `ii_mm.dedup` e as tabelas `refs`/`ref_aliases` do núcleo.

Três identidades distintas, nunca misturadas:
1. REFERÊNCIA (publicação): `canonical_reference_key` do `ii_mm` (plataforma + ID nativo). Grava `refs` com as
   mesmas regras de `Repository.save_analysis`, então uma análise salva depois cai na mesma referência.
   `reference_id` é derivado da chave (determinístico): reingestão em outra máquina gera o mesmo id.
2. ARQUIVO DE MÍDIA: SHA-256 do conteúdo (`be_artifacts`; depois `videos.content_sha256` no `ii_mm`). O mesmo
   arquivo em publicações e plataformas diferentes é UM conteúdo ligado a várias referências.
3. ANÁLISE: `analysis_input_hash` do `ii_mm` (inclui versão do classificador): outro modelo ou outra taxonomia
   gera nova análise; a anterior vira `superseded`, nunca é apagada.

Metadados mudam com o tempo: `be_reference_meta` só acrescenta; o valor corrente é o da observação mais recente;
um campo ausente (None) nunca apaga um valor conhecido; observação antiga que chega atrasada entra no histórico
sem sobrescrever o valor corrente.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from . import _ii_mm  # noqa: F401
from ii_mm.dedup import IdentityError, canonical_reference_key, parse_reference

META_FIELDS = ("caption", "title", "author_handle", "author_name", "hashtags", "published_at", "duration_s",
               "language", "media_type", "view_count", "like_count")


def reference_id_for(canonical_key: str) -> str:
    return "ref_" + hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:20]


def local_native_id(sha256: str) -> str:
    """ID nativo para mídia local sem URL: deriva do conteúdo (nunca inventa uma publicação)."""
    if not (isinstance(sha256, str) and len(sha256) == 64 and all(c in "0123456789abcdef" for c in sha256)):
        raise IdentityError("sha256 inválido para identidade local")
    return "sha-" + sha256[:32]


def clean_url(url: Optional[str]) -> Optional[str]:
    """Remove parâmetros de rastreio/compartilhamento (ex.: `igsh`, `utm_*`, `si`) e fragmento antes de gravar.

    Links compartilhados carregam identificadores de quem compartilhou: não são necessários para a identidade
    e não devem ser persistidos. No YouTube, só `v` (id do vídeo) e `t` são mantidos."""
    if not url:
        return url
    parts = urlsplit(url if "://" in url else "https://" + url)
    host = parts.netloc.lower()
    query = ""
    if "youtube.com" in host:
        q = parse_qs(parts.query)
        query = urlencode([(k, q[k][0]) for k in ("v", "t") if k in q])
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, query, ""))


def resolve_key(platform: Optional[str], url: Optional[str], native_id: Optional[str]) -> Tuple[str, str, str]:
    """(plataforma, id_nativo, chave canônica). URL tem prioridade; ID nu exige plataforma."""
    if url:
        plat, native = parse_reference(url, platform_hint=None)
        if platform and platform != plat:
            raise IdentityError(f"plataforma informada ({platform}) diverge da URL ({plat})")
        if native_id and native_id != native:
            raise IdentityError(f"id informado ({native_id}) diverge do id da URL ({native})")
    elif native_id and platform:
        plat, native = parse_reference(native_id, platform_hint=platform)
    else:
        raise IdentityError("sem identidade confiável: informe URL, ou plataforma + id nativo, ou mídia local")
    return plat, native, canonical_reference_key(native, platform_hint=plat)


@dataclass
class Registration:
    reference_id: str
    canonical_key: str
    platform: str
    created: bool
    alias_conflicts: List[str] = field(default_factory=list)


def register_reference(conn: sqlite3.Connection, platform: str, native_id: str, origin_url: Optional[str],
                       now_iso: str, seen_urls: Iterable[str] = ()) -> Registration:
    """Grava ou encontra a referência. Deve ser chamada DENTRO de uma transação do chamador."""
    if not conn.in_transaction:
        raise RuntimeError("register_reference exige transação aberta pelo chamador")
    key = canonical_reference_key(native_id, platform_hint=platform)
    origin_url = clean_url(origin_url)
    row = conn.execute("SELECT reference_id FROM refs WHERE canonical_key = ?", (key,)).fetchone()
    if row is None:
        row = conn.execute("SELECT reference_id FROM ref_aliases WHERE alias_key = ?", (key,)).fetchone()
    created = row is None
    if created:
        reference_id = reference_id_for(key)
        clash = conn.execute("SELECT canonical_key FROM refs WHERE reference_id = ?", (reference_id,)).fetchone()
        if clash:
            raise IdentityError(f"colisão de reference_id {reference_id}: {clash[0]} × {key}")
        conn.execute("INSERT INTO refs(reference_id, platform, canonical_key, origin_url, author_handle, subject, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (reference_id, platform, key, origin_url, None, None, now_iso))
    else:
        reference_id = row[0]
        if origin_url:
            conn.execute("UPDATE refs SET origin_url = ? WHERE reference_id = ? AND origin_url IS NULL", (origin_url, reference_id))
    conflicts = []
    for url in seen_urls:
        if not url:
            continue
        try:
            alias = canonical_reference_key(url, platform_hint=platform)
        except IdentityError:
            continue
        if alias == key:
            continue
        owners = {r[0] for r in conn.execute("SELECT reference_id FROM refs WHERE canonical_key = ? UNION "
                                             "SELECT reference_id FROM ref_aliases WHERE alias_key = ?", (alias, alias))}
        if owners - {reference_id}:
            conflicts.append(alias)  # a URL já identifica outra publicação: nunca redireciona em silêncio
            conn.execute("INSERT INTO issues(video_pk, analysis_id, kind, description, blocking, created_at) VALUES (NULL,NULL,'conflict',?,1,?)",
                         (f"alias {alias} pertence a outra referência; não associado a {reference_id}", now_iso))
        elif not owners:
            conn.execute("INSERT INTO ref_aliases(alias_key, reference_id, seen_url, created_at) VALUES (?,?,?,?)",
                         (alias, reference_id, clean_url(url), now_iso))
    return Registration(reference_id, key, platform, created, conflicts)


def _order_key(observed_at: Optional[str], recorded_at: str) -> str:
    return observed_at or recorded_at


def current_metadata(conn: sqlite3.Connection, reference_id: str) -> Dict[str, Any]:
    out: Dict[str, Tuple[str, int, Any]] = {}
    for r in conn.execute("SELECT field, value_json, observed_at, recorded_at, meta_id FROM be_reference_meta WHERE reference_id = ?",
                          (reference_id,)):
        k = (_order_key(r["observed_at"], r["recorded_at"]), r["meta_id"])
        if r["field"] not in out or k > out[r["field"]][:2]:
            out[r["field"]] = (k[0], k[1], json.loads(r["value_json"]))
    return {f: v[2] for f, v in out.items()}


def metadata_history(conn: sqlite3.Connection, reference_id: str, field_name: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT meta_id, field, value_json, source_id, observed_at, recorded_at FROM be_reference_meta WHERE reference_id = ?"
    args: list = [reference_id]
    if field_name:
        sql += " AND field = ?"
        args.append(field_name)
    return [dict(r, value=json.loads(r["value_json"])) for r in conn.execute(sql + " ORDER BY meta_id", args)]


def record_metadata(conn: sqlite3.Connection, reference_id: str, source_id: int, metadata: Dict[str, Any],
                    observed_at: Optional[str], now_iso: str) -> List[str]:
    """Acrescenta ao histórico os campos com valor novo. Devolve os campos cujo valor CORRENTE mudou."""
    before = current_metadata(conn, reference_id)
    for name in META_FIELDS:
        value = metadata.get(name)
        if value is None or value == "" or value == []:
            continue  # ausência não apaga o que se sabe
        if name in before and before[name] == value:
            continue  # mesmo valor corrente: nada a registrar
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        conn.execute("INSERT INTO be_reference_meta(reference_id, field, value_json, source_id, observed_at, recorded_at) "
                     "VALUES (?,?,?,?,?,?)", (reference_id, name, encoded, source_id, observed_at, now_iso))
    after = current_metadata(conn, reference_id)
    changed = sorted(f for f in after if before.get(f) != after.get(f))
    if "author_handle" in changed:  # projeção do valor corrente na coluna usada pelo filtro de autor do catálogo
        conn.execute("UPDATE refs SET author_handle = ? WHERE reference_id = ?", (after["author_handle"], reference_id))
    return changed


def references_sharing_media(conn: sqlite3.Connection, sha256: str) -> List[str]:
    """Todas as referências cujo arquivo de mídia (verificado) tem este conteúdo, em qualquer plataforma."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT reference_id FROM be_artifacts WHERE sha256 = ? AND kind = 'video' AND state IN ('verified','superseded') "
        "ORDER BY reference_id", (sha256,))]
