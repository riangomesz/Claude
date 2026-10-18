"""Fixture do catálogo LEGADO do Projeto-MVP em banco temporário (reprodução do `no such table`).

Causa raiz observada (commit c6845a4):
- `instagram_items` só é criada por `core/instagram_importer.init_instagram_db`, cujo módulo importa
  `cv2` (via core.ingestion/markdown_exporter). Sem OpenCV instalado, nenhum teste consegue criar a tabela-base.
- Os demais módulos (`account_connection`, `curation`, `media_acquisition`, `content_miner`) só fazem
  `ALTER TABLE instagram_items` e falham com "no such table" se rodarem antes dela.
- `sqlite3.connect()` num caminho inexistente cria um arquivo vazio, transformando "banco ausente" em
  "tabela ausente".

Correção para testes: extrair o DDL da tabela-base do código-fonte (sem importar o módulo pesado)
e aplicar as funções de esquema na ordem de dependência, sempre num banco temporário.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path
from typing import List

SCHEMA_ORDER = (
    ("core.account_connection", "ensure_connection_schema"),
    ("core.curation", "ensure_curation_columns"),
    ("core.media_acquisition", "ensure_media_schema"),
    ("core.trash_manager", "ensure_trash_schema"),
    ("core.content_miner", "ensure_miner_schema"),
)


def extract_base_ddl(projeto_dir: Path) -> List[str]:
    """Lê `init_instagram_db` por AST e devolve o CREATE TABLE e os CREATE INDEX de instagram_items."""
    src = (Path(projeto_dir) / "core" / "instagram_importer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "init_instagram_db")
    stmts = []
    for node in ast.walk(func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = node.value.strip()
            if sql.upper().startswith(("CREATE TABLE IF NOT EXISTS INSTAGRAM_ITEMS", "CREATE INDEX IF NOT EXISTS")) and "instagram_items" in sql:
                stmts.append(sql)
    if not stmts or not stmts[0].upper().startswith("CREATE TABLE"):
        raise RuntimeError("DDL de instagram_items não encontrado em init_instagram_db")
    return stmts


def build_legacy_catalog(db_path: Path, projeto_dir: Path) -> None:
    db_path = Path(db_path)
    if db_path.name.lower() == "catalog.sqlite":
        raise RuntimeError("a fixture nunca escreve num arquivo chamado catalog.sqlite")
    with sqlite3.connect(str(db_path)) as conn:
        for sql in extract_base_ddl(projeto_dir):
            conn.execute(sql)
    root = str(Path(projeto_dir).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    import importlib
    for mod, fn in SCHEMA_ORDER:
        getattr(importlib.import_module(mod), fn)(db_path)
