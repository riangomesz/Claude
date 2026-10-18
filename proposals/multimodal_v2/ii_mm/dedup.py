"""Identidade de referências e deduplicação (Tarefa 08).

Duas camadas de identidade:
1. `canonical_reference_key(platform, url_or_id)`: identidade da PUBLICAÇÃO (plataforma + ID nativo).
   URLs diferentes (www, m., /reel/ vs /reels/ vs /p/, parâmetros de rastreio) da mesma publicação
   produzem a mesma chave. IDs nativos preservam maiúsculas: shortcodes do Instagram distinguem caixa.
2. `content_sha256`: identidade do CONTEÚDO. O mesmo arquivo salvo por publicações diferentes é um vídeo só.

`analysis_input_hash(doc)` identifica a ENTRADA de uma análise: reprocessar com a mesma entrada é no-op;
qualquer mudança gera nova versão (a anterior fica `superseded`, nunca é apagada).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from .contract import canonical_json

_IG = re.compile(r"^/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,64})/?")
_YT_SHORTS = re.compile(r"^/(?:shorts|live|embed)/([A-Za-z0-9_-]{6,20})")
_TT = re.compile(r"^/@[^/]+/video/(\d{6,25})")
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{5,64}$")
HOST_PLATFORM = {
    "instagram.com": "instagram", "instagr.am": "instagram",
    "youtube.com": "youtube", "youtu.be": "youtube",
    "tiktok.com": "tiktok", "x.com": "x", "twitter.com": "x", "vimeo.com": "vimeo",
}


class IdentityError(ValueError):
    pass


def _host(netloc: str) -> str:
    h = netloc.lower().split("@")[-1].split(":")[0]
    for prefix in ("www.", "m.", "mobile.", "vm."):
        if h.startswith(prefix):
            h = h[len(prefix):]
    return h


def parse_reference(url_or_id: str, platform_hint: Optional[str] = None) -> Tuple[str, str]:
    """Devolve (plataforma, id_nativo). Levanta IdentityError se não houver identidade confiável."""
    raw = str(url_or_id or "").strip()
    if not raw:
        raise IdentityError("referência vazia")
    if "://" not in raw and "/" not in raw:
        if not platform_hint or not _BARE_ID.match(raw):
            raise IdentityError(f"ID nu sem plataforma ou inválido: {raw!r}")
        return platform_hint, raw
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    host = _host(parts.netloc)
    platform = HOST_PLATFORM.get(host)
    if platform is None:
        raise IdentityError(f"host não reconhecido: {host}")
    path = parts.path or "/"
    if platform == "instagram":
        m = _IG.match(path)
        if m:
            return platform, m.group(1)
    elif platform == "youtube":
        if host == "youtu.be":
            vid = path.strip("/").split("/")[0]
            if _BARE_ID.match(vid):
                return platform, vid
        m = _YT_SHORTS.match(path)
        if m:
            return platform, m.group(1)
        v = parse_qs(parts.query).get("v", [None])[0]
        if v and _BARE_ID.match(v):
            return platform, v
    elif platform == "tiktok":
        m = _TT.match(path)
        if m:
            return platform, m.group(1)
    elif platform in ("x", "vimeo"):
        m = re.search(r"/(?:status/)?(\d{5,25})(?:/|$)", path)
        if m:
            return platform, m.group(1)
    raise IdentityError(f"não foi possível extrair o ID da publicação: {raw!r}")


def canonical_reference_key(url_or_id: str, platform_hint: Optional[str] = None) -> str:
    platform, native = parse_reference(url_or_id, platform_hint)
    if platform_hint and platform_hint != platform:
        raise IdentityError(f"plataforma informada ({platform_hint}) diverge da URL ({platform})")
    return f"{platform}:{native}"


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


VOLATILE_KEYS = ("review_history", "classification_runs")


def analysis_input_hash(doc: Dict[str, Any]) -> str:
    """Hash do conteúdo analítico (exclui histórico de revisão e log de execuções)."""
    stable = {k: v for k, v in doc.items() if k not in VOLATILE_KEYS}
    return hashlib.sha256(canonical_json(stable).encode("utf-8")).hexdigest()
