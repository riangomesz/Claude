# Avaliação humana: 30 a 50 vídeos

Etapa 12 da Missão Suprema 03. **Nenhum resultado de avaliação foi produzido nesta missão:** não há rótulos humanos de vídeos reais. Os testes usam rótulos sintéticos só para conferir as contas. Este documento descreve o fluxo que o curador executa no Estágio 2. Os números que saírem dele são a primeira medição real do classificador.

Implementação:
- `ii_mm/evaluation.py`: amostra, planilha, validação e concordância;
- `tools/avaliacao.py`: linha de comando;
- testes em `tests/test_evaluation.py`, inclusive o caminho completo, a partir do snapshot do modo sombra.

## 1. Por que este desenho

| Decisão | Motivo |
|---|---|
| Amostra de **30 a 50** itens, estratificada pelo tipo de resultado do modo sombra (concordam, só o atual, só o novo, nenhum) | Com o catálogo dominado por concordâncias, uma amostra simples quase não veria divergências |
| Semente fixa (`20261019`), lista registrada em `<planilha>.amostra.json` | Outra pessoa consegue refazer a mesma amostra |
| Planilha **cega** por padrão | Mostrar a sugestão do classificador ancora o revisor e infla a concordância |
| Uma coluna por categoria (1, 0 ou vazio) | Um vídeo pode ter várias categorias; vazio significa "não revisei" e o item fica fora |
| Revisor obrigatório por linha | Rastreabilidade |
| Concordância em **contagens** (concorda presente ou ausente, falso positivo, falso negativo) | Com menos de 30 itens a taxa é instável. Abaixo de 30 o relatório **recusa** dar taxa; a partir de 30, a taxa sai sempre junto com o tamanho da amostra |
| O rótulo humano é a referência, não a verdade | Duas pessoas podem discordar. Para medir isso, rotule a mesma amostra com dois revisores e compare as planilhas |

## 2. Passo a passo

Pré-requisito: o modo sombra já rodou sobre o snapshot do catálogo (`GUIA_WINDOWS_POWERSHELL.md`, seção E), em `$Trabalho\sombra`. Os comandos usam `$Pacote` e `$Trabalho` do guia.

**1. Gerar a amostra e a planilha cega**

```powershell
py -3 -I -B -X utf8 "$Pacote\tools\avaliacao.py" amostra --sombra "$Trabalho\sombra" --out "$Trabalho\planilha_avaliacao.csv" --n 40
```

- Gera `planilha_avaliacao.csv` (UTF-8 com BOM, abre no Excel) e `planilha_avaliacao.amostra.json`.
- A URL e a legenda vêm do snapshot, aberto só para leitura.
- Textos que começam com `=`, `+`, `-` ou `@` recebem apóstrofo, para não virar fórmula.
- O comando nunca sobrescreve arquivos.

**2. Rotular**

Para cada linha:
1. Abrir o vídeo pela URL.
2. Marcar `1` nas categorias que se aplicam e `0` nas que não se aplicam.
3. Preencher `revisor` e `data`.
4. Anotar ambiguidades em `observacoes`.

Linhas sem nenhuma marca ficam fora da avaliação. Não consulte os relatórios do modo sombra durante a rotulagem.

As colunas são exatamente as nove categorias de `ii_mm/evidence_rules.CATEGORIES`:

| Categoria | Marcar 1 quando o vídeo… |
|---|---|
| `conhecimento` | explica um conceito ou curiosidade, sem necessariamente ensinar um procedimento |
| `tutorial` | ensina um procedimento que dá para seguir, passo a passo |
| `demonstracao_ferramenta` | mostra ou apresenta uma ferramenta, aplicativo ou plataforma específica |
| `automacao` | trata de automação de fluxo (n8n, Zapier, webhooks, agentes) |
| `motion_design` | tem animação gráfica ou tipografia animada como assunto ou elemento central |
| `edicao_audiovisual` | trata de corte, transição, ritmo, cor ou som como assunto |
| `marketing_vendas` | promove produto, serviço ou curso, ou ensina venda e captação ("link na bio", cupom, leads) |
| `cinematografia` | trata de câmera, lente, enquadramento ou linguagem cinematográfica |
| `referencia_estetica` | vale pela estética ou direção de arte, sem explicar como foi feito |

**3. Calcular a concordância**

```powershell
py -3 -I -B -X utf8 "$Pacote\tools\avaliacao.py" concordancia --sombra "$Trabalho\sombra" --rotulos "$Trabalho\planilha_avaliacao.csv" --out "$Trabalho\concordancia.json"
```

- Se a planilha tiver erro de preenchimento (categoria desconhecida, valor diferente de 1/0/vazio, item duplicado, revisor ausente), o comando lista as linhas e **não calcula nada** (código 1).
- O relatório traz, para o classificador **atual** (rótulo legado mapeado) e para o **novo**:
  - contagens por categoria;
  - itens idênticos ao humano;
  - itens com algum erro.

**4. Registrar e devolver**

Devolva ao Claude Cloud:
- `concordancia.json`;
- `planilha_avaliacao.amostra.json`;
- a planilha preenchida;
- as observações sobre categorias ambíguas.

A planilha contém URLs e legendas de posts. Se forem privadas, envie só os arquivos agregados e o registro da amostra.

## 3. Como ler o resultado (sem decidir por ele)

- **Falso positivo do novo** numa categoria: abra o `relatorio_sombra.md` do item e veja qual evidência sustentou a categoria. Normalmente é uma pista textual ampla demais (`text_classifier.RULES`).
- **Falso negativo do novo:** veja se faltou evidência (sem transcrição ou sem observação visual) ou regra.
- **Concordância alta só porque quase tudo é ausente:** compare `concorda_presente` com `concorda_ausente`. Categorias raras precisam de mais itens positivos antes de qualquer conclusão.
- Os números são **insumo** para `CRITERIOS_ADOCAO.md` (critério C7). Não existe limiar automático de aprovação: quem decide é o responsável pelo projeto, por escrito.

## 4. O que este fluxo não faz

- Não mede a qualidade das observações visuais. O `ii_mm` garante base e proveniência, não o conteúdo da imagem.
- Não substitui a revisão das divergências item a item (`revisao_divergencias.csv`). A amostra mede o classificador; a revisão das divergências decide casos.
- Não usa o vídeo-piloto `DQV5dm6gCvH` como referência. Ele continua `blocked_missing_evidence` na nuvem.
