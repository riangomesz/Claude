"""Repositório SQLite de referência (Tarefas 07 e 08).

Política de gravação (`save_analysis`):
- Referência identificada por `canonical_reference_key`; URLs alternativas viram aliases.
- Vídeo identificado por `content_sha256`: duas publicações com o mesmo conteúdo apontam para um vídeo só.
- Mesma entrada (input_hash) para o mesmo vídeo = no-op idempotente (devolve a análise existente).
- Entrada diferente = nova análise `current`; a anterior vira `superseded` (encadeada), nunca apagada.
- Mesma publicação com conteúdo de hash diferente = conflito: não sobrescreve; registra issue bloqueante.
- Toda gravação acontece numa única transação.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from ..contract import assert_valid
from ..dedup import analysis_input_hash, canonical_reference_key
from .._matcher import normalize

STOPWORDS = {"de", "da", "do", "das", "dos", "que", "com", "para", "uma", "um", "the", "and", "for", "you", "this",
             "isso", "essa", "esse", "aqui", "voce", "nao", "mais", "como", "por", "sem", "seu", "sua"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


@dataclass
class SaveResult:
    analysis_id: str
    reference_id: str
    video_pk: int
    created: bool                 # False = idempotente (mesma entrada já gravada)
    superseded: Optional[str]     # análise anterior que deixou de ser corrente
    conflict: bool = False


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        if conn.isolation_level is not None:
            raise ValueError("use migrations.connect(): o repositório exige transações explícitas")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------ escrita
    def save_analysis(self, doc: Dict[str, Any], seen_url: Optional[str] = None) -> SaveResult:
        assert_valid(doc)
        ref, video = doc["reference"], doc["video"]
        platform = ref["platform"]
        key = canonical_reference_key(ref.get("origin_url") or video["video_id"], platform_hint=platform)
        sha = video.get("content_sha256")
        now = _now()
        with self.tx() as c:
            row = c.execute("SELECT reference_id FROM refs WHERE canonical_key = ?", (key,)).fetchone()
            if row is None:
                row = c.execute("SELECT reference_id FROM ref_aliases WHERE alias_key = ?", (key,)).fetchone()
            if row is not None and row["reference_id"] != ref["reference_id"]:
                # mesma publicação, outro reference_id: grava sob o ID já registrado e guarda o original
                doc = copy.deepcopy(doc)
                doc["reference"]["original_reference_id"] = ref["reference_id"]
                doc["reference"]["reference_id"] = row["reference_id"]
                ref = doc["reference"]
            input_hash = analysis_input_hash(doc)
            if row is None:
                reference_id = ref["reference_id"]
                if c.execute("SELECT 1 FROM refs WHERE reference_id = ?", (reference_id,)).fetchone():
                    raise sqlite3.IntegrityError(f"reference_id {reference_id} já usado por outra publicação")
                c.execute("INSERT INTO refs(reference_id, platform, canonical_key, origin_url, author_handle, subject, created_at) "
                          "VALUES (?,?,?,?,?,?,?)", (reference_id, platform, key, ref.get("origin_url"),
                                                     ref.get("author_handle"), ref.get("subject"), now))
            else:
                reference_id = row["reference_id"]
            alias_conflict = False
            if seen_url:
                alias = canonical_reference_key(seen_url, platform_hint=platform)
                owner = c.execute("SELECT reference_id FROM refs WHERE canonical_key = ? UNION ALL "
                                  "SELECT reference_id FROM ref_aliases WHERE alias_key = ?", (alias, alias)).fetchall()
                if any(o["reference_id"] != reference_id for o in owner):
                    alias_conflict = True  # a URL já identifica outra publicação: não redireciona em silêncio
                elif alias != key and not owner:
                    c.execute("INSERT INTO ref_aliases(alias_key, reference_id, seen_url, created_at) VALUES (?,?,?,?)",
                              (alias, reference_id, seen_url, now))

            linked = c.execute("SELECT v.video_pk, v.content_sha256 FROM ref_videos rv JOIN videos v USING(video_pk) "
                               "WHERE rv.reference_id = ? ORDER BY v.video_pk", (reference_id,)).fetchall()
            video_pk, conflict = None, False
            if sha:
                hit = c.execute("SELECT video_pk FROM videos WHERE content_sha256 = ?", (sha,)).fetchone()
                video_pk = hit["video_pk"] if hit else None
                if linked and all(r["content_sha256"] and r["content_sha256"] != sha for r in linked):
                    conflict = True
            elif linked:
                video_pk = linked[0]["video_pk"]
            if video_pk is None:
                cur = c.execute("INSERT INTO videos(content_sha256, duration_s, width, height, fps, created_at) VALUES (?,?,?,?,?,?)",
                                (sha, video["duration_s"], video.get("width"), video.get("height"), video.get("fps"), now))
                video_pk = cur.lastrowid
            c.execute("INSERT OR IGNORE INTO ref_videos(reference_id, video_pk, platform_video_id) VALUES (?,?,?)",
                      (reference_id, video_pk, video["video_id"]))
            if conflict:
                c.execute("INSERT INTO issues(video_pk, kind, description, blocking, created_at) VALUES (?,?,?,?,?)",
                          (video_pk, "conflict", f"publicação {key} recebeu conteúdo com SHA-256 diferente do já registrado", 1, now))
            if alias_conflict:
                c.execute("INSERT INTO issues(video_pk, kind, description, blocking, created_at) VALUES (?,?,?,?,?)",
                          (video_pk, "conflict", f"alias {alias} já pertence a outra referência; não foi associado a {reference_id}", 1, now))
                conflict = True

            existing = c.execute("SELECT analysis_id FROM analyses WHERE video_pk = ? AND input_hash = ?",
                                 (video_pk, input_hash)).fetchone()
            if existing:
                return SaveResult(existing["analysis_id"], reference_id, video_pk, False, None, conflict)

            analysis_id = f"an_{video_pk}_{input_hash[:16]}"
            prev = c.execute("SELECT analysis_id FROM analyses WHERE video_pk = ? AND status = 'current'", (video_pk,)).fetchone()
            run = (doc.get("classification_runs") or [{}])[-1]
            c.execute("INSERT INTO analyses(analysis_id, video_pk, schema_version, classifier_version, input_hash, status, created_at, document_json) "
                      "VALUES (?,?,?,?,?,'current',?,?)", (analysis_id, video_pk, doc["schema_version"],
                                                           run.get("classifier_version"), input_hash, now, _j(doc)))
            if prev:
                c.execute("UPDATE analyses SET status = 'superseded', superseded_by = ? WHERE analysis_id = ?",
                          (analysis_id, prev["analysis_id"]))
            self._insert_children(c, analysis_id, doc)
            return SaveResult(analysis_id, reference_id, video_pk, True, prev["analysis_id"] if prev else None, conflict)

    def _insert_children(self, c: sqlite3.Connection, aid: str, doc: Dict[str, Any]) -> None:
        c.executemany("INSERT INTO segments(analysis_id, segment_id, t_start_s, t_end_s, text, source) VALUES (?,?,?,?,?,?)",
                      [(aid, s["segment_id"], s["t_start_s"], s["t_end_s"], s["text"], s.get("source")) for s in doc["transcript"]])
        c.executemany("INSERT INTO evidence(analysis_id, evidence_id, status, source_type, claim, t_start_s, t_end_s, ref, tag, basis, provenance_json) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      [(aid, e["evidence_id"], e["status"], e["source_type"], e["claim"], e.get("t_start_s"), e.get("t_end_s"),
                        e.get("ref"), e.get("tag"), e.get("basis"), _j(e["provenance"])) for e in doc["evidence"]])
        for cat in doc["categories"]:
            c.execute("INSERT INTO categories(analysis_id, category, support, auto_review_state) VALUES (?,?,?,?)",
                      (aid, cat["category"], cat["support"], cat.get("review_state", "pending")))
            rows = [(aid, cat["category"], e, "pro") for e in cat.get("evidence_ids", [])]
            rows += [(aid, cat["category"], e, "contra") for e in cat.get("contradicting_evidence_ids", [])]
            rows += [(aid, cat["category"], e, "context") for e in cat.get("context_evidence_ids", [])]
            c.executemany("INSERT OR IGNORE INTO category_evidence(analysis_id, category, evidence_id, role) VALUES (?,?,?,?)", rows)
        c.executemany("INSERT INTO tools(analysis_id, name, status) VALUES (?,?,?)",
                      [(aid, t["name"], t["status"]) for t in doc["tools"]])
        c.executemany("INSERT OR IGNORE INTO techniques(analysis_id, technique, level) VALUES (?,?,?)",
                      [(aid, t["technique"], t["level"]) for t in doc["techniques"]])
        c.executemany("INSERT OR IGNORE INTO search_terms(analysis_id, term) VALUES (?,?)",
                      [(aid, t) for t in sorted(self.search_terms(doc))])

    @staticmethod
    def search_terms(doc: Dict[str, Any]) -> set:
        texts = [doc["reference"].get("subject") or ""]
        texts += [e["claim"] for e in doc["evidence"] if e["status"] in ("transcript_claim", "metadata_claim", "observed_visual")]
        terms = {w for t in texts for w in normalize(t).split() if len(w) >= 3 and w not in STOPWORDS}
        terms |= {f"cat:{c['category']}" for c in doc["categories"]}
        terms |= {f"tool:{normalize(t['name'])}" for t in doc["tools"]}
        terms |= {f"tech:{t['technique']}" for t in doc["techniques"]}
        terms |= {f"tag:{e['tag']}" for e in doc["evidence"] if e.get("tag")}
        terms |= {f"attr:{e['tag']}:{k}={v}" for e in doc["evidence"] if e.get("tag") and e["status"] == "observed_visual"
                  for k, v in ((e.get("extra") or {}).get("attributes") or {}).items()}
        return terms

    # ------------------------------------------------------------------ leitura
    def get_document(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT document_json FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
        return json.loads(row["document_json"]) if row else None

    def current_analysis_id(self, reference_id: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT a.analysis_id FROM ref_videos rv CROSS JOIN analyses a ON a.video_pk = rv.video_pk "
            "WHERE rv.reference_id = ? AND a.status = 'current' ORDER BY a.created_at DESC, a.analysis_id LIMIT 1",
            (reference_id,)).fetchone()
        return row["analysis_id"] if row else None

    def analysis_history(self, video_pk: int) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT analysis_id, status, superseded_by, classifier_version, created_at FROM analyses "
            "WHERE video_pk = ? ORDER BY created_at, analysis_id", (video_pk,))]

    def references_for_video(self, video_pk: int) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT reference_id FROM ref_videos WHERE video_pk = ? ORDER BY reference_id", (video_pk,))]

    def resolve_reference(self, url_or_id: str, platform: Optional[str] = None) -> Optional[str]:
        key = canonical_reference_key(url_or_id, platform_hint=platform)
        row = self.conn.execute("SELECT reference_id FROM refs WHERE canonical_key = ? UNION "
                                "SELECT reference_id FROM ref_aliases WHERE alias_key = ?", (key, key)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ pendências
    def add_issue(self, kind: str, description: str, video_pk: Optional[int] = None,
                  analysis_id: Optional[str] = None, blocking: bool = False) -> int:
        with self.tx() as c:
            return c.execute("INSERT INTO issues(video_pk, analysis_id, kind, description, blocking, created_at) VALUES (?,?,?,?,?,?)",
                             (video_pk, analysis_id, kind, description, int(blocking), _now())).lastrowid

    def open_issues(self, video_pk: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM issues WHERE resolved_at IS NULL"
        args: tuple = ()
        if video_pk is not None:
            sql += " AND video_pk = ?"
            args = (video_pk,)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY issue_id", args)]

    def resolve_issue(self, issue_id: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE issues SET resolved_at = ? WHERE issue_id = ? AND resolved_at IS NULL", (_now(), issue_id))
