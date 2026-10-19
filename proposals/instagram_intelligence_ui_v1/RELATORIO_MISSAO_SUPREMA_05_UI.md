# Relatório — Missão Suprema 05: UI/UX premium e design system com dois temas

## Resumo

Esta entrega é uma interface funcional e sem dependências para a Inteligência Audiovisual, com:

- design system de tokens semânticos claro/escuro;
- dashboard;
- biblioteca;
- fila de curadoria;
- painel de detalhe com 6 abas;
- telas de Análises, Conhecimento, Atividades e Configurações;
- adaptador para o contrato `ii.be.api.v1`.

Tudo roda com fixtures **explicitamente fictícias**. A verificação foi um teste Playwright com 94 checagens, todas aprovadas, e revisão visual de capturas reais.

## Diagnóstico inicial

- O frontend real é `core/panel_minimal.html`: um arquivo único de 274 KB, em JavaScript puro, servido pelo `review_server.py`. Ele foi inspecionado no clone local do Projeto-MVP e **não foi modificado**.
- Escolha decorrente: HTML, CSS e módulos ES nativos, sem build, na mesma convenção do painel atual. Integrar é servir uma pasta estática.
- O contrato `ii.be.api.v1` foi lido no código do backend da MS04 (`api.py`, `search.py`, `scheduler.py`, `curation.py`, `evidence_rules.py`) para que domínio e adaptador usem os nomes reais:
  - 9 categorias;
  - 6 status de evidência;
  - 6 níveis de suporte;
  - triagem `manter`, `revisar_depois` ou `descartar`;
  - 4 notas de avaliação;
  - etapas do agendador;
  - estados de job.

## O que foi implementado

| Entrega | Onde | Estado |
|---|---|---|
| Tokens semânticos claro/escuro, com paridade (71 × 71) | `THEME_TOKENS.css` | feito |
| `data-theme`, preferência do sistema, seletor manual, persistência, sem flash | `index.html` (script inline), `js/theme.js` | feito e testado |
| Componentes (AppShell, Sidebar, Header, ThemeSwitcher, SurfaceCard, MetricCard, StatusBadge, ReferenceCard, FilterBar, SearchInput, ActivityFeed, EmptyState, ErrorState, LoadingState, DetailPanel, Tabs, ConfirmAction, Toast) | `js/ui.js`, `styles/components.css` | feito |
| Dashboard: destaque do catálogo com as 5 métricas, distribuição por categoria, saúde do pipeline, progresso por fase e itens em andamento, atividade recente, ações rápidas, dica de curadoria | `js/views.js` (`overview`) | feito |
| Biblioteca: cartões 9:16, busca, 5 filtros, 4 ordenações, filtro vindo do link, estados vazios | `library` | feito |
| Curadoria: fila de analisadas sem decisão; Manter/Revisar/Descartar e Excelente/Muito bom/Bom/Ruim; confirmação ao descartar | `curation`, aba Curadoria | feito, **só local** na demonstração |
| Painel de detalhe: Vídeo, Metadados, Análise audiovisual, Evidências por status, Curadoria, Conhecimento; estados honestos sem análise | `openDetail` | feito |
| Análises, Conhecimento, Atividades, Configurações | `views.js` | feito, de forma enxuta |
| Automações | `views.js` | estado vazio honesto: nada é disparado |
| Separação entre fixtures e adaptador | `js/data/fixtures.js`, `js/data/adapter.js` | feito |
| Carregamento, vazio e erro (`?simulate=`) | `loadInto`, `adapter.js` | feito e testado |
| Responsivo 1440 → 375 | `components.css` | testado |
| Acessibilidade | ver `UI_ARCHITECTURE.md` | parcialmente testado (ver limites) |
| Documentação | `DESIGN_SYSTEM.md`, `UI_ARCHITECTURE.md`, `HANDOFF_ANTIGRAVITY_UI.md`, este relatório | feito |

## O que funciona e o que usa fixtures

- **Funciona de verdade, independente da fonte de dados:**
  - tema (preferência, persistência, sem flash, segue o sistema);
  - roteamento;
  - filtros, busca e ordenação;
  - painel com abas e teclado;
  - diálogos modais;
  - estados de carregamento, vazio e erro;
  - layout responsivo;
  - movimento reduzido.
- **Usa fixtures** (marcado com "Modo demonstração" no topo e "demo" nos cartões):
  - as 14 referências, autores, links, análises, evidências e atividades;
  - a série de 7 dias do cartão de saúde.

  As métricas são **calculadas** a partir dessas fixtures, não digitadas.
- **Curadoria na demonstração:** muda só a memória da aba e some ao recarregar. A mensagem de confirmação diz "o catálogo real não foi alterado". O teste confere que a decisão não persiste.

## O que falta

- **HttpAdapter não executado:** não havia backend nem autorização para rodá-lo nesta missão. Os nomes de campo vêm do código do backend, não de respostas reais.
- **Lacunas do contrato** para esta UI:
  - a listagem não traz título, duração nem legenda;
  - não há leitura de eventos para a tela Atividades;
  - não há operação com resumo ou facetas da análise;
  - a nota de curadoria não é enviada.
- **Mídia:** sem reprodução de vídeo. A prévia é ilustrativa e diz isso.
- **Ainda não implementado:**
  - ações de reprocessar ou cancelar jobs;
  - edição de categorias e evidências (`accept_category`, `demote_evidence` e afins);
  - paginação visual para catálogos grandes. A grade renderiza tudo o que o adaptador devolve; o HttpAdapter para em 2.000 referências.
- **Não validado no Windows:** fonte, Edge, escala de 125–150%, leitor de tela.

## Build e testes

Não há build: o projeto não tem dependências.

```
node --check js/*.js js/data/*.js                              → sem erros
NODE_PATH=$(npm root -g) node tests/ui_smoke.mjs --shots --out <dir>
→ 94/94 verificações passaram (Playwright 1.56.1, Chromium, Linux)
```

Cobertura do teste:

- 7 larguras × 2 temas: tema do sistema aplicado, sem rolagem horizontal (visão geral, biblioteca, detalhe), painel dentro da tela, console sem erro;
- tema manual, persistência após recarregar, sem flash (script inline com o `app.js` bloqueado), volta para "Sistema";
- primeiro Tab no link de pular; navegação pelas 8 seções com `aria-current`;
- filtros de plataforma e processamento, busca, busca sem resultado, limpar filtros, ordenação, filtro vindo do link, ausência do texto "null";
- detalhe: 6 abas, foco inicial, seta direita, 4 grupos de evidência, Esc devolve o foco, estado sem análise explica o motivo;
- curadoria: confirmação ao descartar, aviso de catálogo inalterado, item sai da fila, não persiste;
- `simulate=error`, `simulate=empty` e `simulate=slow`;
- movimento reduzido.

**Revisão visual real.** As capturas abertas e inspecionadas nesta sessão foram:

- visão geral: 1440 claro e escuro, 1024 escuro, 375 claro;
- biblioteca: 1280 claro, 430 claro;
- detalhe: 1440 claro, 390 escuro.

As demais capturas foram geradas e passaram nas checagens automáticas, mas não foram inspecionadas uma a uma.

Defeitos achados pela revisão visual e corrigidos:

1. Títulos da atividade recente cortados em 4 letras. O texto passou a ficar empilhado com a data.
2. Colunas desalinhadas nas linhas do pipeline. Agora as colunas têm largura fixa.
3. Rótulos das barras ilegíveis. Passaram a ser códigos de 3 letras, com nome completo em `aria-label` e `title`.
4. Botões do destaque com altura colapsada em telas de até 430 px.
5. Prévia do detalhe ocupando a primeira tela do celular.
6. "null" literal na barra de resultados (`replaceChildren(null)`).
7. Anel de foco no título após a troca de rota.
8. Selo "pendente" mais chamativo que "sucesso".
9. Texto discreto do tema claro com contraste de 3,1:1. Agora fica em 7,1:1 sobre superfície sólida e 4,5:1 no ponto mais escuro do fundo.
10. Selo "Aguardando curadoria" em itens ainda sem análise.

## Limitações da nuvem

- Sem acesso ao Windows, ao Projeto-MVP em execução, ao Antigravity ou a um backend `ii_be` em execução.
- Validação feita só em Chromium/Linux, com fontes de fallback do contêiner.
- Contraste calculado nos tokens. Superfícies translúcidas e gradientes não foram medidos pixel a pixel.
- Sem telemetria de custo nesta sessão, então não há valor de custo a informar.

## Arquivos (todos novos)

Todos ficam em `proposals/instagram_intelligence_ui_v1/` (17 arquivos, cerca de 2.600 linhas):

- `index.html`, `THEME_TOKENS.css`, `styles/components.css`
- `js/app.js`, `js/theme.js`, `js/ui.js`, `js/icons.js`, `js/domain.js`, `js/views.js`
- `js/data/adapter.js`, `js/data/fixtures.js`
- `tests/ui_smoke.mjs`, `.gitignore` (ignora `tests/output/`)
- `DESIGN_SYSTEM.md`, `UI_ARCHITECTURE.md`, `HANDOFF_ANTIGRAVITY_UI.md`, `RELATORIO_MISSAO_SUPREMA_05_UI.md`

Nada fora dessa pasta foi alterado. Conferido no fim da missão:

| Alvo | Estado |
|---|---|
| backend MS04 (`claude/instagram-intelligence-backend-supreme-04`) | `dac131f`, intacto |
| `main` | `34ee777`, intacto |
| clone do Projeto-MVP | `c6845a4`, sem alterações |
| RC1 multimodal, `ii_be`, ii-bridge, n8n, Vault | não tocados |

Sem merge, sem PR, sem deploy.

## Branch e commit

- Branch: `claude/instagram-intelligence-uxui-05`, a partir de `dac131f`.
- Commit: o commit que adiciona esta pasta (ver `git log -1` na branch).

## Como visualizar

Rode `python -m http.server 8765 --bind 127.0.0.1` dentro da pasta e abra `http://127.0.0.1:8765/`. Detalhes em `HANDOFF_ANTIGRAVITY_UI.md`.

## Próximos passos para o Antigravity

1. Abrir a demonstração no Windows (Edge e Chrome, escala de 100% e 150%) e rodar `tests/ui_smoke.mjs`.
2. Conferir a olho os dois temas, sobretudo o desfoque das superfícies e a fonte Segoe.
3. Decidir com o usuário a integração: rota paralela no `review_server` com adaptador para `/api/*`, ou direto sobre o `ii_be` depois da adoção.
4. Em seguida, validar o `HttpAdapter` contra uma **cópia** do banco: paginação, etag e idempotência da curadoria.
5. Levar ao backend as lacunas do contrato listadas acima.
