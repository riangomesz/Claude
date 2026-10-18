"""Carrega proposals/classification/text_matcher.py por caminho, sem alterar sys.path."""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "classification" / "text_matcher.py"
_spec = importlib.util.spec_from_file_location("ii_text_matcher", _PATH)
text_matcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(text_matcher)

normalize = text_matcher.normalize
compile_keyword = text_matcher._compile
RankedMatcher = text_matcher.RankedMatcher
