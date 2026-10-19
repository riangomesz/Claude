import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

# Só código do Projeto-MVP entra na cópia: nada de storage/, review_notes/, .git, bancos ou mídia.
PROJETO_SAFE_DIRS = ("core", "config")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite", "*.sqlite3", "*.db", "*.bak", "*.mp4", "*.jpg", "*.png", "*.webp")
_COPY = None


def projeto_dir():
    """Cópia descartável (uma por processo) do código de PROJETO_MVP_DIR, ou None se a variável não existir.

    Os testes nunca leem módulos nem gravam nada no diretório indicado: importar `core` direto do projeto
    vivo criaria __pycache__ lá dentro, e a Missão Suprema 03 proíbe alterar o clone, nem temporariamente.
    """
    global _COPY
    src = os.environ.get("PROJETO_MVP_DIR")
    if not src:
        return None
    if _COPY is None:
        src_path = Path(src).resolve()
        missing = [d for d in PROJETO_SAFE_DIRS if not (src_path / d).is_dir()]
        if missing:
            raise RuntimeError(f"PROJETO_MVP_DIR sem as pastas esperadas: {missing}")
        tmp = Path(tempfile.mkdtemp(prefix="ii_mvp_copia_"))
        atexit.register(shutil.rmtree, tmp, True)
        for d in PROJETO_SAFE_DIRS:
            shutil.copytree(src_path / d, tmp / d, ignore=_IGNORE)
        _COPY = tmp
    return _COPY
