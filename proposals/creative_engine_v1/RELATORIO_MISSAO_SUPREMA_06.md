# Relatório — Missão Suprema 06: Creative Intelligence Engine

**Branch:** `claude/instagram-intelligence-creative-engine-06` (de `claude/instagram-intelligence-backend-supreme-04` @ `dac131f`, estado conferido antes de ramificar). Pasta: `proposals/creative_engine_v1/`. Sem merge, PR ou deploy. Sem telemetria de custo disponível: nenhum valor é informado.

## Resumo

Foi implementado e testado um motor que, para cada referência já analisada, cria uma **investigação versionada**, planeja e executa **especialistas simulados** com contrato e proveniência, **reconcilia** as afirmações pela força da evidência, e gera um **dossiê** (Markdown, JSON, CSV, manifest) com engenharia reversa, plano de reprodução, adaptações para Rian Rocha IA e Objetaria, roteiro e plano de produção. Há API local, workflow n8n inativo e exportação para staging do Obsidian. **Os especialistas são MOCK**: eles estruturam as evidências recebidas, não interpretam imagem nem áudio. O valor demonstrado é o fluxo, as garantias e o formato do dossiê; a qualidade analítica real depende de provedores que ainda não foram conectados.

## Legenda

IMPLEMENTADO = código na branch · TESTADO = coberto por teste automatizado executado · SIMULADO = roda com dados/provedores sintéticos · PENDENTE = não feito · BLOQUEADO = depende de algo indisponível.

## Tarefas

| # | Tarefa | Estado |
|---|---|---|
| 01 | Objeto de investigação versionado (`ii.ce.investigation.v1`) | IMPLEMENTADO, TESTADO |
| 02 | Taxonomia em 4 domínios ligada a evidências | IMPLEMENTADO, TESTADO |
| 03 | Orquestrador de especialistas (4 perfis, adaptadores intercambiáveis) | IMPLEMENTADO, TESTADO, SIMULADO (mocks) |
| 04 | Planejador por necessidade, com motivo e limites | IMPLEMENTADO, TESTADO |
| 05 | Pacote mínimo por especialista; texto de terceiros só em `data` | IMPLEMENTADO, TESTADO |
| 06 | Reconciliação (concordância ≠ verdade; contradições; revisão humana) | IMPLEMENTADO, TESTADO |
| 07 | Decomposição em blocos (cenas medidas, sem afirmar movimento) | IMPLEMENTADO, TESTADO (parcial) |
| 08 | Hipóteses de produção (observada/comprovada/mencionada/sugerida/hipótese/ausente) | IMPLEMENTADO, TESTADO |
| 09 | Plano de reprodução em 10 seções | IMPLEMENTADO, TESTADO (estrutura); conteúdo genérico por técnica |
| 10 | Perfis comerciais versionados em JSON | IMPLEMENTADO, TESTADO |
| 11 | Motor de adaptação (múltiplas propostas por referência) | IMPLEMENTADO, TESTADO |
| 12 | Briefing, roteiro, storyboard textual, shot list, timeline, assets, prompts, plano, checklist | IMPLEMENTADO, TESTADO; determinístico |
| 13 | Dossiê automático (00–08, README, manifest, JSON/CSV) | IMPLEMENTADO, TESTADO |
| 14 | Exportação Obsidian em staging | IMPLEMENTADO, TESTADO |
| 15–16 | Workflow n8n importável + README | IMPLEMENTADO; estrutura TESTADA; **não importado em n8n real** |
| 17 | Aprovação e revisão humanas | IMPLEMENTADO, TESTADO |
| 18 | Demonstração ponta a ponta | IMPLEMENTADO, TESTADO (13/13), SIMULADO |
| 19 | Testes essenciais | 44 testes OK (ver abaixo) |
| 20 | Handoff | IMPLEMENTADO |
| 21 | Este relatório | — |

## Contratos novos

`ii.ce.investigation.v1`, `ii.ce.specialist_request.v1`, `ii.ce.specialist_result.v1`, `ii.ce.business_profile.v1`, `ii.ce.dossier_manifest.v1`, `ii.ce.status.v1`, `ii.ce.api.v1`. Os contratos da MS04 (`ii.be.*`) e da RC1 (`ii.reference_analysis.v2`) não foram alterados; o motor lê a análise corrente que eles produzem.

## Testes e resultados

| Suíte | Resultado |
|---|---|
| `creative_engine_v1/run_tests.py` | **44 testes OK** (~6 s) |
| `backend_engine_v1/run_tests.py` (regressão da dependência) | 94 testes OK |
| `python -m ii_ce.demo` | **13/13 verificações**; dois runs geram os mesmos arquivos (conferido por `diff`) |
| API real por HTTP (`ii_ce.serve`, `curl`) | `health` e `open_investigation` responderam em loopback |

Cobertura dos testes: idempotência (abrir, executar, dossiê, eventos); versionamento sem sobrescrever; concorrência (4 workers executam cada tarefa uma vez; 3 aberturas simultâneas criam 1 investigação); queda e retomada por lease; ausência de evidências; contradição entre especialistas; concordância sem promoção de estado; movimento só por quadros = `supported_static`; provedor indisponível (progresso preservado, retomada); saída malformada, com evidência fora do pacote e com campos extras; injeção em legenda (fica em `data`); provedor com rede recusado; seleção de evidências por especialista; decisões humanas (atores automáticos recusados, preservadas entre versões e reexecuções, não promovem estado); aprovação de modelo pago e limites de custo; planejador por tipo, profundidade e limite de chamadas; perfis como dados e perfil inválido; CSV contra fórmulas; integridade do dossiê (hash por arquivo, citações ↔ índice, sem caminhos locais); Markdown externo neutralizado; Obsidian (links entre vídeos, bloco do curador preservado, recusa de cofre); migrações (idempotência e checksum); tabelas `be_*` intactas; eventos entregues uma vez, sem perda em falha do consumidor; API (validação, esquema fechado, Host, Content-Type, loopback, n8n não aprova); workflow (inativo, sem credenciais, só 127.0.0.1, operações e campos existentes, sem nó Code, sem etapa de decisão humana).

## Demonstração (sintética)

Executa: ingestão e pipeline do `ii_be` → investigação `deep` (referência classificada como `complexo`, 4 especialistas) → **queda simulada** no especialista criativo → retomada por outro objeto após o lease → divergência registrada em `tecnica:legenda_sobreposta` → dossiê v1 → duas revisões humanas → dossiê v2 (v1 arquivado) → nova investigação `standard` que preserva as revisões e marca a anterior como `superseded` → staging do Obsidian (reexportação sem alteração) → 16 eventos entregues uma vez ao JSONL.

**Exemplo de dossiê gerado:** `exemplo_dossie_sintetico/dossie/ref_051a0dcdb3819bd6e22b/` (comece por `README.md`, `00_RESUMO_EXECUTIVO.md`, `02_ENGENHARIA_REVERSA.md`, `08_PERGUNTAS_EM_ABERTO.md`). Os arquivos Markdown e o `manifest.json` levam o aviso "DADOS SINTÉTICOS… especialistas são MOCK". O piloto `DQV5dm6gCvH` **não** foi usado: não está disponível aqui. Nada foi simulado como se tivesse sido assistido.

## Workflow n8n

`n8n/ii_creative_engine_investigacao.workflow.json` (21 nós, inativo, sem credenciais, só 127.0.0.1). Os nós de Obsidian e de eventos vêm **desabilitados** (ativação progressiva). Não há nó de aprovação: o backend recusa atores `n8n:`, então aprovação de modelo pago, revisão e aprovação do dossiê são de uma pessoa. Versão-alvo e requisitos em `n8n/README.md`.

## Integrações

| Integração | Estado |
|---|---|
| `ii_be` (mesmo SQLite, pipeline, curadoria, artefatos) | usado, TESTADO |
| `ii_mm` (análise corrente, trava e escrita atômica do Obsidian) | usado, TESTADO |
| Gemini / Argon / Claude / Codex como provedores | **PENDENTE**: só existem como perfis de trabalho e mocks; nenhuma chamada externa foi feita |
| Modelos pagos | não usados; fluxo de aprovação TESTADO com mock pago |
| n8n real | **BLOQUEADO** (não disponível); só validação estrutural |
| Windows, Antigravity, mídia privada, piloto `DQV5dm6gCvH`, Vault real | **BLOQUEADO / NÃO TESTADO** |

## Riscos e limitações honestas

1. **Mock ≠ modelo.** Não há evidência de que um modelo real produza afirmações úteis nas chaves canônicas esperadas; é o maior risco. A reconciliação agrupa por `key`: provedores reais precisam normalizar para o vocabulário (ver handoff §6).
2. **Adaptações são geradas por regras e pelos "ângulos" dos perfis JSON.** O conteúdo dos dois perfis foi escrito por mim a partir das descrições da missão (sem dados privados) e precisa da sua revisão antes de qualquer uso. O roteiro traz estrutura e intenção por bloco; **o texto falado fica "[a definir]"** até haver um agente criativo.
3. **Plano de reprodução e erros comuns vêm de conhecimento geral** (`knowledge_base.py`), rotulado como tal, sem parâmetros numéricos. Não substituem teste.
4. **Decomposição em blocos depende de candidatos a cena medidos**; sem eles há um bloco único. Transições não são classificadas.
5. **Prazo de provedor:** a chamada roda em thread; depois do prazo ela é cancelada por sinal, mas um provedor que ignore o sinal pode continuar em segundo plano (as threads são `daemon`).
6. **`max_calls` e `max_usd` são aplicados no planejamento; `max_usd` também na execução.** O prazo é por chamada, não por investigação. Não há reenfileiramento de tarefas `failed` por API (só `blocked_*`).
7. **Tabelas `ce_*` no mesmo arquivo do `ii_be`**: migração aditiva, mas exige backup e uso de cópia. O outbox `ce_events` não tem retenção.
8. **O dossiê atual não passou por leitura humana com dados reais.** Estrutura e honestidade das seções foram testadas; utilidade prática não.
9. Os eventos do `ii_be` (`be_outbox`) e os do motor criativo (`ce_events`) são trilhas separadas; o painel precisaria ler as duas.

## Pendências do Windows

Rodar as duas suítes; rodar o demo; importar o workflow em n8n de teste; testar `ii_ce.serve` numa cópia do banco; ingerir o piloto `DQV5dm6gCvH`; gerar um dossiê real; avaliar com um humano se ele ajuda a produzir.

## Próxima etapa executável

1. No Windows, validar o pacote e gerar o dossiê do piloto com os mocks (custo zero). 2. Com o dossiê real em mãos, decidir **qual especialista conectar primeiro** e autorizar um provedor. 3. Implementar esse adaptador seguindo `SpecialistProvider` (um arquivo), com aprovação de custo e chaves no backend. 4. Rodar o piloto de novo e comparar com o dossiê MOCK. 5. Só então ativar o workflow em n8n de teste.
