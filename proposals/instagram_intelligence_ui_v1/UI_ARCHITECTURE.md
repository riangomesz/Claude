# Arquitetura da UI — Instagram Intelligence UI v1

## Decisão

HTML, CSS e módulos ES nativos, **sem dependências e sem build**. É a mesma convenção do painel atual (`core/panel_minimal.html` servido pelo `review_server.py`, só biblioteca padrão), então a integração consiste em servir uma pasta estática. Não foi adotado React, Vite ou npm: cada um traria cadeia de build, lockfile e superfície de ataque sem ganho para uma tela de curadoria local.

## Estrutura

```
proposals/instagram_intelligence_ui_v1/
├── index.html            # shell; script inline sem flash de tema
├── THEME_TOKENS.css      # primitivos + tokens semânticos claro/escuro
├── styles/components.css # componentes, layout e responsivo
├── js/
│   ├── app.js            # entrada: tema, adaptador, rotas por hash, AppShell
│   ├── theme.js          # preferência light|dark|system, persistência e matchMedia
│   ├── ui.js             # h() + componentes reutilizáveis
│   ├── icons.js          # ícones de traço inline (strings estáticas)
│   ├── domain.js         # enums do backend → rótulos (categorias, status, etapas)
│   ├── views.js          # telas e painel de detalhe
│   └── data/
│       ├── adapter.js    # DemoAdapter | HttpAdapter (ii.be.api.v1)
│       └── fixtures.js   # DADOS FICTÍCIOS de demonstração
└── tests/ui_smoke.mjs    # Playwright: 7 larguras × 2 temas + fluxos
```

## Fluxo

1. O script inline do `<head>` lê `localStorage["ii-theme"]` e define `data-theme` antes do primeiro paint.
2. `app.js` cria o adaptador (`createAdapter()`), escuta `hashchange` e redesenha `Sidebar + main`.
3. Cada view devolve `{ title, subtitle, body }`. `loadInto()` mostra o esqueleto, chama o adaptador e troca o conteúdo pelo resultado ou por `ErrorState` com nova tentativa.
4. O painel de detalhe vive em `#layer`, fora da árvore redesenhada. Depois de uma decisão de curadoria, só a tela por trás dele é redesenhada.

Rotas: `#/overview`, `#/library`, `#/curation`, `#/analysis`, `#/knowledge`, `#/automations`, `#/activity`, `#/settings`. Filtros podem vir no link (`#/library?processing=falhou`). Eles valem só quando o hash muda; depois disso, quem manda são os controles da tela.

## Fonte de dados

A interface chama só o adaptador e nunca toca as fixtures ou o `fetch` diretamente.

| Método | DemoAdapter | HttpAdapter (`POST /v1/<op>`) |
|---|---|---|
| `overview()` | resumo calculado das fixtures | `list_references` (paginado) + `list_failures` |
| `listReferences()` | fixtures | `list_references` (`items`, `next_cursor`) |
| `getReference(id)` | fixture | `get_reference` + `get_processing` + `get_evidence` + `get_curation` + `get_classification` |
| `listActivity()` | fixtures | **vazio**: a API não expõe o outbox de eventos para leitura |
| `registerCuration(id, …)` | muda só a memória da aba (`persisted: false`) | `register_curation` (`triage`/`rating`, `reviewer: "human:<nome>"`, `expected_etag`, `idempotency_key`) |

Seleção pela query string:

- padrão: demonstração;
- `?simulate=slow`, `?simulate=error` ou `?simulate=empty`: estados simulados da demonstração;
- `?api=same-origin&reviewer=<nome>`: HTTP.

Mapeamentos feitos no adaptador, conferidos no código do backend:

- triagem `revisar` ↔ `revisar_depois`;
- estados de job do `ii_be.queue` (`queued`, `claimed`, `running`, `retry_scheduled`, `waiting_dependency`, `completed`, `failed`, `dead_letter`, `cancelled`) → `pending`, `running`, `done` ou `failed`;
- `get_processing.stages` é um objeto por etapa com `status` e `job.last_error`;
- `media_state === "available"`.

Restrições do HttpAdapter:

- **Não foi executado contra um backend.** Os nomes de campo foram lidos no código do `ii_be` (`api.py`, `search.py`, `scheduler.py`, `curation.py`), mas nenhuma chamada real foi feita.
- O servidor `ii_be.http_local` não responde preflight CORS, de propósito, como defesa contra CSRF. Por isso a UI precisa ser servida **na mesma origem** da API, por exemplo como rota estática do `review_server` ou atrás de um proxy reverso. O adaptador só chama caminhos relativos (`/v1/...`).
- Campos que o backend ainda não entrega na listagem (título, duração, legenda) ficam vazios até o detalhe ser aberto. Resumo e facetas da análise não têm operação própria na API e aparecem como "não informado pela fonte".

## Segurança

- Todo dado entra no DOM como nó de texto (`h()` não usa `innerHTML`). Ícones são strings estáticas.
- Links externos usam `rel="noopener noreferrer"`. Os links das fixtures são fictícios e não são clicáveis.
- Na demonstração, a curadoria não sai da aba. A mensagem de confirmação diz isso explicitamente.

## Acessibilidade

- Link "Pular para o conteúdo"; `nav` com rótulo; item ativo com `aria-current="page"`; título focado na troca de rota.
- O painel e os diálogos são modais de verdade: foco preso, Esc fecha, foco devolvido a quem abriu.
- Abas no padrão WAI-ARIA. Barras do gráfico são botões com `aria-label` e `aria-pressed`. Progresso usa `role="progressbar"`.
- Estados de carregamento com `aria-busy`, erros com `role="alert"`, toasts em região `aria-live`.
- `prefers-reduced-motion` respeitado. Contraste dos tokens de texto ≥ 4,5:1 (ver `DESIGN_SYSTEM.md`).

## Responsivo

| Largura | Comportamento |
|---|---|
| ≥ 1280 | bento de 2 colunas + coluna lateral de 344 px |
| ≤ 1279 | coluna lateral desce para baixo do bento, em 2 colunas |
| ≤ 1023 | margem de 16 px; o destaque empilha orbes e ações |
| ≤ 767 | navegação inferior fixa, coluna única, grade de 2 cartões, painel em tela cheia, rótulos do seletor de tema viram só ícones |
| ≤ 430 | orbes menores, metadados em 1 coluna, indicador de status oculto, botões do destaque empilhados |
