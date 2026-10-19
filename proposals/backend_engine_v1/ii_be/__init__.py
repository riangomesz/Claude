"""ii_be: motor operacional (backend) do Instagram Intelligence sobre o núcleo `ii_mm` (proposta isolada).

O núcleo `ii_mm` (proposals/multimodal_v2) é usado como dependência, nunca copiado: este pacote acrescenta
ingestão, fila persistente, scheduler com dependências, cache incremental, artefatos, curadoria, eventos,
consulta, gateway de modelos (somente simulado) e observabilidade. Somente biblioteca padrão.
"""
from . import _ii_mm  # noqa: F401  (torna `ii_mm` importável a partir de proposals/multimodal_v2)

__version__ = "0.1.0"
ENGINE_ID = "ii_be-0.1.0"
