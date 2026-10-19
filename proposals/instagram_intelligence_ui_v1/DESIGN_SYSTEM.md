# Design system — Instagram Intelligence UI v1

Linguagem visual de SaaS premium: superfícies translúcidas sobre um fundo lavanda (ou azul-noite no escuro), cantos generosos, sombras suaves, ações primárias em pílula escura e um único acento em gradiente azul→violeta. A referência visual recebida foi usada só como linguagem (layout em bento, orbes ligados por uma ponte de gradiente, gráfico de barras arredondadas, cartão de destaque em gradiente). Nenhum conteúdo financeiro foi reaproveitado.

## Camadas de tokens (`THEME_TOKENS.css`)

1. **Primitivos**: paletas `lav`, `blue`, `violet`, `ink`, `slate`, `green`, `amber`, `red`; tipografia, espaçamento, raios, alturas, durações, z-index. Não dependem de tema.
2. **Semânticos por tema**: `:root[data-theme="light"]` e `:root[data-theme="dark"]`, com o mesmo conjunto de 71 tokens em cada tema (paridade conferida por script). O tema escuro foi desenhado à parte, sem `filter: invert()`.
3. **Componentes** (`styles/components.css`) usam só tokens semânticos. Variáveis locais por instância: `--h` (barra), `--p` (progresso), `--c` (cor de categoria).

Sem JavaScript, o bloco `@media (prefers-color-scheme: dark) :root:not([data-theme])` segue o sistema.

| Grupo | Tokens principais |
|---|---|
| Fundo | `--bg-canvas`, `--bg-app`, `--bg-app-glow` |
| Superfícies | `--surface`, `--surface-solid`, `--surface-alt`, `--surface-raised`, `--surface-sunken`, `--surface-hover`, `--surface-active`, `--surface-overlay`, `--surface-accent` |
| Texto | `--text-primary`, `--text-secondary`, `--text-muted`, `--text-inverse`, `--on-accent`, `--on-accent-muted` |
| Ação | `--action-primary-bg/-fg/-bg-hover`, `--action-secondary-bg/-fg/-border/-bg-hover` |
| Acento | `--accent-blue`, `--accent-violet`, `--accent-gradient`, `--orb-gradient`, `--orb-bridge` |
| Status | `--status-{info,success,warning,danger,neutral,pending}-{bg,fg}` |
| Gráficos | `--chart-1..9` (uma cor por categoria do classificador), `--chart-track`, `--chart-bar`, `--chart-bar-active` |
| Foco | `--focus-ring`, `--focus-outline` |

## Contraste (calculado sobre os tokens, WCAG 2.x)

Sobre `--surface-solid`:

| Token | Claro | Escuro |
|---|---|---|
| `--text-primary` | 15,5 | 14,3 |
| `--text-secondary` | 8,5 | 7,8 |
| `--text-muted` | 7,1 | 5,1 |
| status `*-fg` | 4,7 a 6,0 | 9,2 a 11,1 |

O texto secundário e o texto discreto do tema claro foram escurecidos nesta missão: o discreto estava em 3,1:1. Medido sobre o ponto mais escuro do fundo lavanda (`#B6C3EC`), o discreto fica em 4,5:1 e o secundário em 5,4:1. Superfícies translúcidas e gradientes não foram medidos pixel a pixel.

## Tipografia, espaço, forma

- Fonte: pilha do sistema (`Inter`, `SF Pro Display`, `Segoe UI Variable Display`, …). Nenhuma fonte é baixada.
- Escala de tamanho: `--fs-2xs` (11) até `--fs-3xl` (44). Os números grandes usam peso leve, como na referência.
- Espaçamento: escala de 4 px (`--space-1..12`). Raios: `--radius-xs..2xl` e `--radius-pill`.
- Alturas de controle: 32, 40 e 48 px. Item de navegação: 44 px (40 px no celular).

## Movimento

- `--dur-fast` 150 ms (hover, cor), `--dur-base` 220 ms (superfícies, abas), `--dur-slow` 300 ms (painel, barras).
- A troca de tema aplica `html.theme-transition` por 320 ms, para não animar cada repintura.
- `prefers-reduced-motion: reduce` zera animações e transições. O teste automatizado confere isso.

## Componentes

Todos estão em `js/ui.js`, com classes em `styles/components.css`.

| Componente | Classe/elemento | Notas |
|---|---|---|
| AppShell | `.app` + `.main` | grade: barra lateral + conteúdo; no celular vira tela cheia com navegação inferior |
| Sidebar | `.sidebar`, `.nav-item[aria-current]` | dica (`.tip`) no hover e no foco; rótulo acessível em `aria-label` |
| Header | `.header`, `.title`, `.header-actions` | título com foco programático na troca de rota |
| ThemeSwitcher | `.segmented.theme-switch` | Claro / Escuro / Sistema, com `aria-pressed` |
| Indicador de status | `.status-pill`, `.status-dot(.live/.error)` | "Modo demonstração", "API local conectada" ou "API indisponível" |
| SurfaceCard | `.card`, `.card-accent` | marca "demo" quando o conteúdo vem das fixtures |
| MetricCard | `.orb`, `.orb.is-focus` | orbes ligados pela ponte de gradiente (`.orbs::before`) |
| StatusBadge | `.badge-{info,success,warning,danger,pending,outline}` | |
| ReferenceCard | `.ref-card`, `.thumb` 9:16 | `aria-pressed` marca o item aberto no painel |
| FilterBar / SearchInput | `.filters`, `.search` | `label` real em cada controle |
| ActivityFeed | `.list.feed` | linhas clicáveis abrem o detalhe |
| EmptyState / ErrorState / LoadingState | `.empty`, `.empty.is-error`, `.skeleton` | erro com `role="alert"` e botão de nova tentativa; carregamento com `aria-busy` |
| DetailPanel | `.detail`, `.overlay` | `role="dialog"`, foco preso, Esc fecha, devolve o foco |
| Tabs | `.tabs`, `.tab[aria-selected]` | padrão WAI-ARIA: setas, Home e End |
| Dialog / ConfirmAction | `.dialog-backdrop`, `.dialog` | `role="alertdialog"`, foco começa em "Cancelar" |
| Toast | `.toast-region` | `aria-live="polite"` |

## Regras de uso

- Componentes nunca usam cor literal. Valor novo entra primeiro como token semântico, nos dois temas.
- Dado de demonstração sempre aparece marcado ("Modo demonstração" no topo e "demo" nos cartões).
- Gradiente só no acento: no orbe em foco, no cartão de saúde, na barra ativa e no progresso. Sem brilho neon.
- Texto externo (legenda, transcrição) entra como nó de texto e nunca como HTML.
