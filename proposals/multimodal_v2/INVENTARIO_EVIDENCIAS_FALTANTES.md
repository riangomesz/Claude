# Inventário de evidências: DQV5dm6gCvH (Missão Cloud 02)

**Status da análise visual: NÃO REALIZADA. Bloqueada por falta de evidências.**
Nenhuma observação visual foi produzida, inferida ou copiada de outra fonte.

## O que foi verificado

| Local | Resultado |
|---|---|
| `riangomesz/Projeto-MVP`, remoto, `refs/heads/main` (`c6845a4`) | Só `main`. Sem `review_notes/`, sem `storage/videos/`, sem frames. Essas pastas estão no `.gitignore`. |
| Clone em `/home/user/projeto-mvp` | Idem. Busca por `pacote_analise_2`, `ii_cobertura_visual`, `ficha_inteligencia_v2*`, `manifesto_pacote*`, `perguntas_de_verificacao*`, `segmentos_transcricao*`, `cortes_detectados*`, `*.jpg/.png/.webp/.mp4`: nenhum resultado. |
| Repositório `riangomesz/Claude` (esta branch) | Sem mídia. |
| Caminhos `C:\Users\...` | Não existem no ambiente cloud e não foram presumidos. |

O que existe versionado sobre o vídeo, e **não substitui** as evidências visuais:
`ii_coverage/config/curation.DQV5dm6gCvH.json` e `narrative_blocks.DQV5dm6gCvH.json` (anotações do curador a partir da transcrição) e os JSONs de fila em `storage/orchestrator_queue/`. Não os usei como observação visual.

## O que precisa ser fornecido

Pasta `Projeto-MVP/review_notes/ii_cobertura_visual/DQV5dm6gCvH/pacote_analise_2/`. A estrutura abaixo foi derivada do código `ii_coverage/fase5.js` (função `pacote`).

### Obrigatórios

| # | Arquivo | Observação |
|---|---|---|
| 1 a 12 | `frames/pNN_<papel>_tNNNNNNms.jpg` (12 JPEG) | Papéis: 4 × `interface_ou_legenda` e 4 pares `corte_antes`/`corte_depois`. Resolução esperada 1080 × 1920. |
| 13 | `manifesto_pacote.json` (`ii.evidence_package.v1`) | Traz o SHA-256 de cada frame, o `t_s` e os segmentos de fala associados. |
| 14 | `perguntas_de_verificacao.json` (`ii.verification_questions.v1`) | As 32 perguntas de verificação. |
| 15 | `segmentos_transcricao.json` | Texto de transcrição automática, tratado como dado não confiável. |
| 16 | `cortes_detectados.json` (`ii.scene_candidates.v1`) | Candidatos a corte (ffmpeg, limiar 0,04). |

### Desejáveis

| Arquivo | Para que serve |
|---|---|
| `ficha_inteligencia_v2.json` (`ii.intelligence.card.v2`) | Comparar a segunda análise com as 17 observações da Fase 5. |
| `manifesto_cobertura.json` e `storyboard.jpg` | Contexto temporal da Fase 4 (12 frames, grade 4 × 3). |
| Relatório da primeira análise (`execucao_*.json`) | Evitar contradição com a primeira análise. |

### Não necessários, e que não devem ser enviados

- O vídeo (`.mp4`): não é preciso para a análise de quadros. Sem ele, movimento contínuo, rolagem e legenda palavra a palavra continuam **não verificáveis**.
- Banco SQLite, `.env`, tokens, `.n8n-files/`, exportação Meta e o job local `job_2026-10-18T18-15-44-488Z_d823ee66` (só referência de proveniência).

## Como fornecer sem publicar no GitHub

1. Anexar diretamente nesta conversa os 12 JPEG e os 4 JSONs obrigatórios (os JPEGs são frames de um Reel de terceiros; por isso não vão para o repositório).
2. Na máquina do Windows, antes de enviar, conferir a integridade: `python verify_package.py <pasta>\pacote_analise_2`. Esse script é somente leitura.
3. Aqui, rodar o mesmo verificador antes de abrir qualquer imagem. Se algum SHA-256 divergir, a análise para.

## Quando as evidências chegarem

1. `verify_package.py` deve sair com código 0.
2. Observar cada frame e registrar os achados como `visual_observations` (tag, `t_s`, `evidence_basis`, `kind`, proveniência com `pacote_id` e SHA-256).
3. Rodar `multimodal_classifier.classify()` e gravar o resultado em `analise_multimodal_v2.json`.
4. Escrever `RELATORIO_AUDIOVISUAL_V2.md` a partir desse JSON, separando observação verificada, afirmação de fala e hipótese.
5. Limites já conhecidos: pares de quadros mostram diferença entre dois instantes, não movimento. Mudanças só na metade superior da tela pontuam pouco na detecção global de cortes (limitação documentada em `fase5.js`).

## Reverificação (2ª tentativa, sessão de 2026-10-18)

Pacote **ainda inacessível**. Verificado de novo, em leitura:

- `riangomesz/Projeto-MVP`: continua só `main` em `c6845a4`, sem pacote, sem mídia.
- `riangomesz/Claude`: branches `main`, `claude/magnific-mcp-http-llrptl` (só `.mcp.json`, outro trabalho, não tocado) e esta. Nenhuma contém JPEG, JSON de pacote ou ficha v2.
- Sistema de arquivos da sessão: `/mnt/user-data/{uploads,outputs,working}` e `/mnt/attach` existem e estão **vazios**; nenhum `p*_ms.jpg`, `manifesto_pacote.json`, `perguntas_de_verificacao.json`, `segmentos_transcricao.json`, `cortes_detectados.json` ou `ficha_inteligencia_v2.json` em lugar algum.

Os 16 arquivos obrigatórios continuam ausentes (12 JPEG e 4 JSONs), assim como a ficha v2. Nenhum hash pôde ser verificado e nenhuma análise visual foi feita.
