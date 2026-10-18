# Integração proposta com os módulos atuais

Nada abaixo foi aplicado ao `Projeto-MVP`. Cada passo é um patch pequeno, para revisão antes de ir ao ambiente do Antigravity.

| Módulo atual | Ponto de integração | Mudança proposta | Risco |
|---|---|---|---|
| `core/curation.py::suggest_editorial_category` | Casamento por `kw in texto` | Trocar por `RankedMatcher`, mantendo a assinatura e as chaves de retorno. Aprovar só com `test_regression_current.py` verde e os defeitos conhecidos corrigidos de forma intencional. | Baixo |
| `core/curation.py::RELEVANT_KEYWORDS` | Tokens ambíguos (`make`, `dev`, `tech`, `edit`) | Revisar a lista com o golden; trocar por frases quando preciso. | Baixo |
| `core/content_miner.py::classify_content_for_rian` | Qualidade usa só largura, altura e fps | Receber o perfil `av_metrics` por vídeo como entrada **opcional** e expor em `breakdown`, sem alterar o score enquanto não houver calibração. | Médio |
| `core/audiovisual_pilot.py` | Gravação só no fim | Registrar cada etapa em `analysis_run` (idempotente por hash). | Médio |
| `core/studio_adapter.py::list_studio_catalog` | Leitura completa e `stat` por linha | Paginação por cursor; `has_media_file` mantido na escrita. | Baixo |
| `temporal_intelligence/*` | Layout 0,448 e limiares de um vídeo | Layout e limiares por vídeo, com `full_frame` como padrão. | Médio |
| `core/review_server.py` (painel) | Sem campo de revisão por categoria | Endpoint de leitura da classificação e de gravação de `review` (token de sessão). | Médio |
| `ii_coverage/fase5.js` | Gera o pacote e as perguntas | Passar a emitir `visual_observations` no formato de `multimodal_classifier`. | Baixo |

Ordem recomendada: 1) fixtures e migrações em banco de teste; 2) `RankedMatcher` em modo sombra; 3) gravação de `evidence`/`classification` em banco de teste; 4) sugestão no painel; 5) calibração.

Regras de proteção: nenhum desses passos roda no `catalog.sqlite` de produção, nenhum toca o n8n ou os processos locais, e a branch `main` do `Projeto-MVP` não é alterada por esta proposta.
