"""Taxonomia de erros e política explícita de nova tentativa (Tarefa 07).

Cada exceção de etapa é classificada numa classe com regra própria; nada é tentado para sempre:

| classe              | o que significa                                   | destino                                         |
|---------------------|---------------------------------------------------|-------------------------------------------------|
| transient           | falha passageira (E/S, rede local, arquivo preso) | retry com backoff exponencial + jitter          |
| timeout             | etapa passou do prazo                             | retry com backoff; esgotado → dead_letter       |
| integration         | ferramenta/serviço local respondeu errado         | retry com backoff; esgotado → dead_letter       |
| model               | modelo externo (só simulado) falhou               | retry com backoff; esgotado → dead_letter       |
| resource_busy       | recurso ocupado (limite, banco travado)           | retry curto; orçamento próprio; não conta falha |
| dependency_missing  | insumo ainda não chegou (artefato, mídia parcial) | waiting_dependency com espera crescente;        |
|                     |                                                   | orçamento próprio esgotado → failed             |
| invalid_input       | entrada inválida (não melhora repetindo)          | failed (exige nova entrada)                     |
| permanent           | erro de programação ou condição irrecuperável     | dead_letter imediato (inspecionável)            |

Exceções desconhecidas contam como `permanent`: melhor parar e inspecionar do que repetir às cegas.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Optional


class StageError(Exception):
    error_class = "permanent"


class TransientError(StageError):
    error_class = "transient"


class StageTimeout(StageError):
    error_class = "timeout"


class IntegrationError(StageError):
    error_class = "integration"


class ModelError(StageError):
    error_class = "model"


class ResourceBusy(StageError):
    error_class = "resource_busy"


class DependencyMissing(StageError):
    error_class = "dependency_missing"


class InvalidInput(StageError):
    error_class = "invalid_input"


class PermanentError(StageError):
    error_class = "permanent"


class Cancelled(StageError):
    """A etapa percebeu um pedido de cancelamento (cooperativo)."""
    error_class = "cancelled"


ERROR_CLASSES = ("transient", "timeout", "integration", "model", "resource_busy", "dependency_missing",
                 "invalid_input", "permanent", "cancelled", "lease_lost")


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, StageError):
        return exc.error_class
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (ConnectionError, BlockingIOError)):
        return "transient"
    if isinstance(exc, OSError):
        return "transient"
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "invalid_input" if isinstance(exc, ValueError) else "permanent"
    return "permanent"


@dataclass(frozen=True)
class Decision:
    state: str                 # retry_scheduled | waiting_dependency | failed | dead_letter
    delay_s: float = 0.0
    counts_as_failure: bool = True
    reason: str = ""


@dataclass
class RetryPolicy:
    base_delay_s: float = 5.0
    max_delay_s: float = 900.0
    jitter: float = 0.2                    # ± fração do atraso (0 desliga)
    busy_delay_s: float = 2.0
    max_busy_retries: int = 20
    dependency_delay_s: float = 30.0
    max_dependency_waits: int = 10
    rng: random.Random = field(default_factory=lambda: random.Random(20261019))
    per_class_max_attempts: Dict[str, int] = field(default_factory=dict)

    def backoff(self, failures: int) -> float:
        raw = min(self.max_delay_s, self.base_delay_s * (2 ** max(0, failures - 1)))
        if self.jitter:
            raw *= 1 + self.rng.uniform(-self.jitter, self.jitter)
        return max(0.0, min(raw, self.max_delay_s))

    def decide(self, error_class: str, failures_so_far: int, max_attempts: int, busy_retries: int = 0,
               dependency_waits: int = 0) -> Decision:
        """`failures_so_far` já inclui a falha atual quando ela conta como falha."""
        limit = self.per_class_max_attempts.get(error_class, max_attempts)
        if error_class == "resource_busy":
            if busy_retries + 1 > self.max_busy_retries:
                return Decision("dead_letter", reason=f"recurso ocupado em {busy_retries + 1} tentativas seguidas")
            return Decision("retry_scheduled", self.busy_delay_s, counts_as_failure=False, reason="recurso ocupado")
        if error_class == "dependency_missing":
            if dependency_waits + 1 > self.max_dependency_waits:
                return Decision("failed", counts_as_failure=False, reason=f"dependência ausente após {dependency_waits + 1} esperas")
            delay = min(self.max_delay_s, self.dependency_delay_s * (2 ** dependency_waits))
            return Decision("waiting_dependency", delay, counts_as_failure=False, reason="aguardando insumo")
        if error_class == "invalid_input":
            return Decision("failed", reason="entrada inválida: repetir não resolve")
        if error_class == "permanent":
            return Decision("dead_letter", reason="erro permanente ou desconhecido")
        if error_class in ("transient", "timeout", "integration", "model", "lease_lost"):
            if failures_so_far >= limit:
                return Decision("dead_letter", reason=f"{failures_so_far} falhas ({error_class}); limite {limit}")
            return Decision("retry_scheduled", self.backoff(failures_so_far), reason=error_class)
        return Decision("dead_letter", reason=f"classe de erro sem regra: {error_class}")


def safe_message(exc: BaseException, limit: int = 300) -> str:
    """Mensagem curta e de uma linha (sem rastreamento, que pode carregar dados de entrada)."""
    text = " ".join(f"{exc.__class__.__name__}: {exc}".split())
    return text[:limit]


def error_class_of(exc: Optional[BaseException]) -> Optional[str]:
    return None if exc is None else classify_exception(exc)
