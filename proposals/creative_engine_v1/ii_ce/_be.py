"""Localiza `ii_be` (e, por ele, `ii_mm`) sem copiá-los. Ordem: II_BE_DIR ou `proposals/backend_engine_v1` vizinha."""
import os
import sys
from pathlib import Path

_default = Path(__file__).resolve().parents[2] / "backend_engine_v1"
II_BE_DIR = Path(os.environ.get("II_BE_DIR") or _default).resolve()
if not (II_BE_DIR / "ii_be" / "__init__.py").is_file():
    raise ImportError(f"backend ii_be não encontrado em {II_BE_DIR} (defina II_BE_DIR)")
if str(II_BE_DIR) not in sys.path:
    sys.path.insert(0, str(II_BE_DIR))

import ii_be  # noqa: E402,F401
