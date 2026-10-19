"""Localiza o núcleo `ii_mm` sem copiá-lo.

Ordem: variável `II_MM_DIR` (pasta que contém `ii_mm/`) ou a árvore `proposals/multimodal_v2` vizinha.
O núcleo da RC1 é usado como está: nada aqui altera arquivos dele.
"""
import os
import sys
from pathlib import Path

_default = Path(__file__).resolve().parents[2] / "multimodal_v2"
II_MM_DIR = Path(os.environ.get("II_MM_DIR") or _default).resolve()
if not (II_MM_DIR / "ii_mm" / "__init__.py").is_file():
    raise ImportError(f"núcleo ii_mm não encontrado em {II_MM_DIR} (defina II_MM_DIR)")
if str(II_MM_DIR) not in sys.path:
    sys.path.insert(0, str(II_MM_DIR))

import ii_mm  # noqa: E402

II_MM_VERSION = getattr(ii_mm, "__version__", "desconhecida")
