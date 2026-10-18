# Riscos e rollback

Riscos encontrados ou confirmados nas Missões 01 e 02. **Estado** indica o que foi feito no `ii_mm` (corrigido e testado) e o que continua no legado (só documentado, sem alteração).

## Riscos no Projeto-MVP (legado, não alterado)

| # | Risco | Evidência | Impacto | Mitigação proposta | Estado |
|---|---|---|---|---|---|
| L1 | Conexões SQLite não fechadas: `with sqlite3.connect()` deixa a conexão viva até o GC de ciclos (25 ocorrências) | Medição em `tests/test_ms02_sqlite.py`: funções legadas deixam 1 ou 2 conexões vivas após o retorno; com `closing()`, zero | Windows: arquivo do banco travado por tempo indeterminado (backup, troca de banco, pastas temporárias) | `patches/legacy_close_sqlite_connections.diff` (validado numa cópia) | Patch pronto, **não aplicado** |
| L2 | `instagram_items` só nasce em módulo que importa `cv2`; os outros fazem `ALTER` e quebram com `no such table` | `LegacyNoSuchTableReproductionTest` | Testes legados dependem do banco de produção | Fixture `legacy_fixture.py` (só para testes) | Mitigado para testes |
| L3 | Shortcodes em minúsculas em nomes de arquivo | `git ls-files storage/` | Colisão entre itens que só diferem na caixa | `safe_name` com hash (no `ii_mm`); no legado, não renomear sem migração | Documentado |
| L4 | `ensure_connection_schema` cria pastas relativas ao código, não ao banco | Descoberto na Missão 02 (pastas vazias criadas no clone pela fixture, já removidas) | Testes com banco temporário poluem a árvore do projeto | Fixture redireciona; no legado, derivar do `db_path` como `trash_manager` faz | Mitigado para testes |
| L5 | Limiares do `temporal_intelligence` calibrados num único vídeo | Auditoria 2 | Tipos de evento enviesados | Adaptador trata como hipótese | Documentado |
| L6 | `content_miner` produz score 0 a 100 e "tier" sem calibração | Matriz de compatibilidade | Pode ser lido como confiança | Não importar como evidência | Documentado |

## Riscos no `ii_mm` (corrigidos na Missão 02)

| # | Risco | Correção | Teste |
|---|---|---|---|
| A1 | NFC/NFD geravam evidências diferentes | `contract.nfc` | `A1UnicodeNormalizationTest` |
| A2 | Quadros amostrados "provavam" mecanismo de movimento | `temporal_variation` + mecanismo como hipótese; `temporal_sequence` exige `video_clip` | `A2…` |
| A3 | Revisão humana herdada com outras evidências | `stale_review_ref` | `A3StaleReviewTest` |
| A4/A5 | Colisão de alias e `reference_id` divergente | Alias recusado com issue; `original_reference_id` | `A4A5IdentityCollisionTest` |
| A6 | Markdown/HTML ativo vindo da transcrição (imagem remota, wikilink) | `_esc` neutraliza | `A6MarkdownInjectionTest` |
| A7/A8 | Nomes de arquivo reservados no Windows e colisão por caixa | `safe_name` com hash | `A7A8FileNameTest` |
| A9/A10 | Gateway derrubado por exceção; corpo sem limite | `TRANSIENT` sem vazar detalhes; limite de 256 KB | `A9A10GatewayHardeningTest` |
| A11 | Entradas sem limite de tamanho | `MAX_RECORDS`, `MAX_TEXT_CHARS` | `A11InputSizeLimitsTest` |
| A12 | Chave de primeiro nível com erro de digitação aceita | Lista de chaves + prefixo `x_` | `A12UnknownTopLevelKeysTest` |
| A13 | Interface reconhecida pela aparência contava como identificação | Só nome/logotipo legível; fonte `external_knowledge` | `A13ExternalKnowledgeTest` |
| C1 | Dois executores rodavam a mesma etapa | Posse e lease (M008) | `C1PipelineLeaseTest` |
| T08 | Filtro sem valor existente varria o catálogo | Checagem de existência por índice | `T08ZeroResultFiltersTest` |
| F1 | Fixture legada criava pastas dentro do clone | Redirecionamento e teste de isolamento em cópia | `LegacyFixtureIsolationTest` |

## Riscos residuais (aceitos e conhecidos)

1. **Sem validação em dados reais:** tudo foi testado com dados sintéticos e o clone publicado (`c6845a4`). O estado local do Antigravity pode divergir.
2. **Vocabulários sem calibração:** pistas, tags e léxico são escolhas iniciais. O modo sombra existe justamente para medir isso com revisão humana.
3. **Windows não testado:** caminhos, travas de arquivo, WAL em pasta sincronizada e versão do SQLite precisam ser conferidos no Estágio 1.
4. **Observador é a fonte da observação:** o `ii_mm` garante base e proveniência coerentes, mas não verifica o conteúdo da imagem.
5. **Lease depende do relógio local:** em vários processos na mesma máquina não há problema; em máquinas diferentes, os relógios precisam estar sincronizados.

## Rollback por estágio

| Estágio | O que foi criado | Como desfazer | Verificação |
|---|---|---|---|
| 1 | Cópia de `proposals/` fora do projeto | Apagar a pasta | Nenhum arquivo do projeto foi tocado (`git status` limpo) |
| 2 (sombra) | `relatorio_sombra.*` na pasta `--out` | Apagar a pasta | O catálogo legado foi aberto em `mode=ro` (o SQLite recusa escrita) |
| 2 (banco v2) | `storage/ii_v2.sqlite` (+ `-wal`/`-shm`) | Apagar os três arquivos | O catálogo legado não referencia o banco v2 |
| 2 (n8n) | Workflow **novo** e segredo HMAC | Desativar e apagar o workflow; revogar o segredo | Workflows existentes não foram editados |
| 2 (staging) | Notas em pasta de staging | Apagar a pasta | O Vault real nunca foi escrito (`assert_staging`) |
| 3 | Decisão humana específica | Definido no momento da decisão | Exige plano próprio |
| Patch L1 (se aplicado) | Mudança em 6 arquivos do `core/` | `git revert` do commit do patch | Rodar os testes legados antes e depois |

**Critérios para acionar o rollback:**
- qualquer escrita detectada em `catalog.sqlite` vinda do `ii_mm`;
- qualquer arquivo novo dentro do Vault;
- testes opt-in falhando no Windows sem explicação registrada;
- divergência inexplicada no modo sombra num item que o curador considera óbvio.
