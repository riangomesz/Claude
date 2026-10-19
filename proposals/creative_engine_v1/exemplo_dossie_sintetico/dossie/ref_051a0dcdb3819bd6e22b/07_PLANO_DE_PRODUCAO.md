# 07 · Plano de produção

> ⚠ **DADOS SINTÉTICOS DE DEMONSTRAÇÃO — nenhum vídeo real foi assistido; especialistas são MOCK**
>
> Referência `ref_051a0dcdb3819bd6e22b` · investigação `inv_0077c0f60aa15fa431b0` (versão 1) · estado: **complete** · ii_ce/0.1.0
> Verificação: **sustentada** · **aparece no quadro (movimento não comprovado)** · **dita, não vista** · **hipótese** · **contradição em aberto** · **não verificada**. Concordância entre especialistas não eleva o estado.

## A. Plano de reprodução técnica (baseado nas evidências)

### 1. Resultado pretendido

Reproduzir os princípios observados: legenda_sobreposta, punch_in, split_screen. Reprodução de PRINCÍPIOS, não cópia do vídeo.

### 2. Materiais necessarios

- roteiro e texto de tela
- material bruto (gravação de tela, vídeo ou imagens geradas)
- áudio (fala e/ou trilha)
- acesso a: CapCut
- acesso a: n8n

### 3. Softwares possiveis

- comprovados_ou_mencionados: ["CapCut", "n8n"]
- sugeridos_por_categoria: ["editor de vídeo com camada de texto", "qualquer editor com escala/keyframe", "editor com camadas"]
- nota: "sugestões por categoria; software específico NÃO confirmado"

### 4. Etapas de producao

- (dito pelo autor) Nesse vídeo vou mostrar o passo a passo no CapCut [ev:a5a2ccf2]
- (dito pelo autor) Primeiro abre a timeline, em seguida clica em legendas automáticas [ev:00c8db8d]
- (inferido das técnicas) Preparo (roteiro, material, ferramentas): definir roteiro e mensagem ¦ reunir material e ferramentas listados _sem evidência_
- (inferido das técnicas) Montagem (planos e cortes): split_screen: definir a grade; posicionar camadas; alinhar duração e áudio _sem evidência_
- (inferido das técnicas) Texto e legendas: legenda_sobreposta: definir o texto e a divisão em linhas; criar camada de texto; posicionar dentro da área segura vertical; sincronizar com a fala _sem evidência_
- (inferido das técnicas) Ênfase e movimento: punch_in: duplicar o trecho ou aplicar keyframe de escala; recortar o enquadramento; alinhar ao ponto de ênfase da fala _sem evidência_
- (inferido das técnicas) Acabamento e exportação: revisar áudio e legibilidade ¦ exportar no formato de destino _sem evidência_

### 5. Configuracoes conhecidas

- {"evidence_id": "ev_6024c746e79be206e01b", "value": "1080x1920 @ 30.0 fps, 24.0 s", "status": "medido"}

### 6. Parametros que precisam de teste

- fonte, tamanho e contorno
- percentual de escala
- proporção da divisão
- se foi corte seco ou animado
- se é gerada automaticamente ou manual

### 7. Ordem de execucao

- **Preparo (roteiro, material, ferramentas)**: definir roteiro e mensagem | reunir material e ferramentas listados
- **Montagem (planos e cortes)**: split_screen: definir a grade; posicionar camadas; alinhar duração e áudio
- **Texto e legendas**: legenda_sobreposta: definir o texto e a divisão em linhas; criar camada de texto; posicionar dentro da área segura vertical; sincronizar com a fala
- **Ênfase e movimento**: punch_in: duplicar o trecho ou aplicar keyframe de escala; recortar o enquadramento; alinhar ao ponto de ênfase da fala
- **Acabamento e exportação**: revisar áudio e legibilidade | exportar no formato de destino

### 8. Criterios de qualidade

- foco claro em um dos lados
- legível em tela de celular sem zoom
- nitidez preservada após o zoom
- resultado comparado lado a lado com a referência apenas como estudo, nunca publicado como cópia

### 9. Erros comuns

_conhecimento geral de produção, NÃO observado neste vídeo_

- contraste baixo sobre fundo claro
- perda de nitidez em fonte de baixa resolução
- reenquadramento que corta o rosto
- texto sob a interface da plataforma
- áudio de duas fontes competindo

### 10. Verificacoes finais

- texto legível em tela de celular
- áudio sem cortes bruscos
- formato 9:16 e duração de destino
- itens 'não verificados' da engenharia reversa testados ou marcados como hipótese
- revisão humana das hipóteses aceitas

## B. Plano de produção do vídeo original (PROPOSTA)

### `prop_13cab15c8aed72b10ffd`

- **Pré-produção**: fechar roteiro e mensagem; aprovar direção de arte; listar assets
- **Produção**: produzir os planos da shot list; gravar/gerar áudio
- **Pós-produção**: montar a timeline; aplicar texto e ênfases; etalonagem e mixagem; exportar 9:16
- **Entrega**: revisão humana; checklist final

Assets: asset_01, asset_02, asset_03, asset_04, asset_05, trilha

Prompts sugeridos (a testar; não são os do autor): ver `estruturados/prompts_prop_13cab15c8aed72b10ffd.json`.

Checklist de entrega:

- [ ] mensagem central clara nos primeiros segundos
- [ ] texto legível em celular
- [ ] sem cópia de plano, texto ou identidade da referência
- [ ] conteúdo gerado por IA identificado quando exigido
- [ ] restrições do perfil respeitadas: não prometer resultado que o vídeo não demonstre; identificar conteúdo gerado por IA quando a plataforma exigir; não imitar rosto, voz ou marca de terceiros sem autorização
- [ ] aprovação humana registrada

### `prop_63c2ec98bcca5cdd75ca`

- **Pré-produção**: fechar roteiro e mensagem; aprovar direção de arte; listar assets
- **Produção**: produzir os planos da shot list; gravar/gerar áudio
- **Pós-produção**: montar a timeline; aplicar texto e ênfases; etalonagem e mixagem; exportar 9:16
- **Entrega**: revisão humana; checklist final

Assets: asset_01, asset_02, asset_03, asset_04, asset_05, trilha

Prompts sugeridos (a testar; não são os do autor): ver `estruturados/prompts_prop_63c2ec98bcca5cdd75ca.json`.

Checklist de entrega:

- [ ] mensagem central clara nos primeiros segundos
- [ ] texto legível em celular
- [ ] sem cópia de plano, texto ou identidade da referência
- [ ] conteúdo gerado por IA identificado quando exigido
- [ ] restrições do perfil respeitadas: não mostrar medidas, prazos ou preços não confirmados; mostrar o produto real quando a imagem for apresentada como produto; indicar quando uma imagem for ilustração gerada por IA
- [ ] aprovação humana registrada

