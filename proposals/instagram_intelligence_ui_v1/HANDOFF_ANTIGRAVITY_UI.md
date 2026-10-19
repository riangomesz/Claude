# Handoff para o Antigravity — Instagram Intelligence UI v1

Branch: `claude/instagram-intelligence-uxui-05`, criada a partir de `claude/instagram-intelligence-backend-supreme-04` (`dac131f`). Pasta: `proposals/instagram_intelligence_ui_v1/`. Nada foi integrado ao Projeto-MVP, ao `main` ou ao backend.

## 1. Ver a interface (Windows, sem instalar nada)

```powershell
cd <clone>\proposals\instagram_intelligence_ui_v1
python -m http.server 8765 --bind 127.0.0.1
# abrir http://127.0.0.1:8765/
```

Use `http://`: abrir o `index.html` direto do disco (`file://`) bloqueia os módulos ES.

Variações da demonstração:

| URL | O que mostra |
|---|---|
| `/` | demonstração com 14 referências fictícias |
| `/?simulate=slow#/library` | esqueleto de carregamento por 1,6 s |
| `/?simulate=error` | estado de erro com "Tentar de novo" |
| `/?simulate=empty` | catálogo vazio |

## 2. Rodar o teste visual/funcional

Precisa de Node 18+ e do Playwright com Chromium instalados globalmente:

```powershell
npm i -g playwright; npx playwright install chromium
$env:NODE_PATH = (npm root -g)
node tests\ui_smoke.mjs --shots --out tests\output
```

O teste percorre 7 larguras (1440/1280/1024/768/430/390/375) × 2 temas. Em cada uma confere ausência de rolagem horizontal, painel dentro da tela, tema aplicado e console limpo. Depois testa os fluxos:

- tema manual, persistência e ausência de flash;
- foco inicial pelo teclado;
- navegação pela barra lateral;
- filtros, busca e ordenação;
- filtro vindo do link;
- painel de detalhe: abas, setas, Esc e devolução de foco;
- estado sem análise;
- curadoria local com confirmação de descarte;
- estados simulados;
- movimento reduzido.

As capturas vão para `tests/output/`, que está fora do git.

**Pontos para conferir a olho no Windows.** A nuvem só viu o Chromium do Linux:

- renderização da fonte (Segoe UI Variable em vez de Inter);
- desfoque das superfícies (`backdrop-filter`) no Edge;
- escala de 125–150% do Windows;
- navegação real por teclado com leitor de tela (NVDA/Narrador).

## 3. Integração com o backend real (não executada)

1. Servir a pasta na **mesma origem** da API `ii_be.http_local`, que não responde CORS, de propósito. Caminhos possíveis:
   - rota estática no `review_server`;
   - proxy reverso que mande `/v1/*` para a API e `/` para esta pasta.
2. Abrir com `?api=same-origin&reviewer=<seu-nome>`. A curadoria exige revisor humano: o backend recusa atores automáticos.
3. Validar com uma cópia do banco, nunca com o original. Pontos a conferir:
   - `list_references` paginado;
   - `get_processing.stages` (objeto por etapa);
   - `get_curation.etag` e conflito de etag em duas abas;
   - `register_curation` idempotente.
4. Lacunas conhecidas do contrato para a UI:
   - a listagem não traz título, duração nem legenda;
   - não há operação de leitura de eventos (a tela Atividades fica vazia em modo HTTP);
   - não há operação com resumo ou facetas da análise;
   - a nota de curadoria não é enviada (o campo é só local).

## 4. Integração com o painel atual (decisão do usuário)

Duas opções, sem mexer no `panel_minimal.html` até haver autorização:

- **A — paralela:** servir esta pasta numa rota nova (ex.: `/ui/`) do `review_server`, ao lado do painel atual. Exige um adaptador fino para os endpoints `/api/*` existentes (`/api/items`, `/api/triage`, `/api/rate`, …), se o backend `ii_be` ainda não estiver no ar.
- **B — sobre o `ii_be`:** usar o `HttpAdapter` direto, depois da adoção do backend (ver `proposals/backend_engine_v1/PLANO_ADOCAO_BACKEND.md`).

## 5. O que não fazer

- Não apontar o `HttpAdapter` para o banco de produção sem cópia de segurança.
- Não tratar números das fixtures como reais. A interface marca "Modo demonstração" e "demo" sempre que as usa.
- Não remover os avisos de que a curadoria demonstrativa não altera o catálogo.
