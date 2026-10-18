# Baseline atual: `proposals/` (Tarefa 01)

Data: 2026-10-18. Branch: `claude/instagram-intelligence-audit-4ezsd1`, commit `5bd6088`.
Este documento registra só o que é novo em relação às auditorias anteriores.

## Ambiente medido

| Item | Valor |
|---|---|
| Python | 3.13.16 (stdlib apenas; sem `pytest` e sem `coverage`) |
| SQLite | 3.45.1 |
| CPU / RAM | 4 vCPU x86_64 / 16 GB |
| Anexos de mídia | `/mnt/user-data/uploads` e `/mnt/attach` vazios (bloqueio já registrado no inventário) |

## Suíte baseline

Executor novo: `python3 run_tests.py`. Mede tudo de uma vez, inclusive o matcher.

| Módulo de teste | Testes | Resultado |
|---|---|---|
| `test_text_matcher` | 6 | OK |
| `test_multimodal_classifier` | 17 | OK |
| `test_regression_current` | 4 | 3 OK, 1 pulado sem `PROJETO_MVP_DIR` (passa com o clone `c6845a4`) |
| `test_verify_package` | 6 | OK |
| **Total** | **33** | **32 OK, 1 pulado** |

**Divergência com o último relatório:** o "27 aprovados e 1 pulado" contava só `multimodal_v2`. Esse "27" já incluía o teste pulado, então eram 26 aprovados mais 1 pulado. O matcher (6 testes) ficava de fora.

## Cobertura real (stdlib `trace`, `tools/stdlib_coverage.py`)

| Módulo | Linhas cobertas | Lacunas relevantes |
|---|---|---|
| `classification/text_matcher.py` | ~97% | (nenhuma relevante) |
| `multimodal_classifier.py` | ~94% | Ramos de erro de `validate_signals` (tag, base e tempo inválidos em parte) e de `validate_analysis` |
| `verify_package.py` | ~83% | `main`, manifesto vazio e frame ausente não testados |

A cobertura de linhas alta esconde falta de **casos malformados**. Os defeitos abaixo foram reproduzidos.

## Defeitos novos encontrados no código isolado

| # | Módulo | Defeito | Reprodução |
|---|---|---|---|
| B1 | `verify_package.py` | Manifesto com JSON inválido ou que não é objeto derruba o verificador com exceção em vez de relatar o problema. | `manifesto_pacote.json` = `[` |
| B2 | `verify_package.py` | Entrada de frame sem `file` resolve para a própria pasta e é relatada como "fora do pacote" (mensagem errada). Entradas duplicadas não são detectadas. | `{"frames":[{"pacote_id":"P01"}]}` |
| B3 | `multimodal_classifier.validate_signals` | Segmento sem `start`/`end` levanta `KeyError`, não `SignalError`. Duração negativa ou não numérica é aceita. | `{"duration_s": -1}` |
| B4 | `multimodal_classifier.validate_analysis` | Categoria sem a chave `evidence` em documento `concluida` levanta `KeyError`. | `{"status":"concluida","categories":[{"category":"tutorial"}]}` |
| B5 | `multimodal_classifier.classify` | IDs de evidência (`categoria:n`) só são únicos dentro de um documento e mudam com a ordem de entrada. Isso impede deduplicação e persistência. | Dois vídeos geram `tutorial:1` |
| B6 | `multimodal_classifier` | `sys.path.insert` no import é efeito colateral global. | (inspeção) |

B1 a B4 são corrigidos nesta missão com testes. B5 e B6 são resolvidos pelo pacote novo `ii_mm/`, que tem IDs de evidência por conteúdo e imports relativos. O módulo v1 fica preservado para compatibilidade.

## Contratos existentes e lacunas para integração

- `ii.multimodal_analysis.v1` (v1): estados `verified_visual`, `measured`, `claimed_transcript`, `claimed_metadata`, `hypothesis`. Não tem `insufficient`/`unverified`, contradição explícita, ferramentas, técnicas, segmentos, histórico de revisão, hash de conteúdo nem plataforma.
- A missão pede os estados `observed_visual`, `measured_signal`, `transcript_claim`, `metadata_claim`, `inference` e `unverified`. O contrato v2 (`ii.reference_analysis.v2`) adota esses nomes, e um mapeamento v1→v2 fica documentado e testado.
- Dependências: só stdlib. `multimodal_classifier` depende de `classification/text_matcher.py` por caminho relativo.

## Decisão de organização

- Código novo vai em `proposals/multimodal_v2/ii_mm/` (pacote) e os testes em `proposals/multimodal_v2/tests/`.
- Arquivos v1 ficam intactos, exceto pelas correções B1 a B4.
- `run_tests.py` agrega as duas suítes.
