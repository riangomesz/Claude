# 02 · Engenharia reversa

> ⚠ **DADOS SINTÉTICOS DE DEMONSTRAÇÃO — nenhum vídeo real foi assistido; especialistas são MOCK**
>
> Referência `ref_051a0dcdb3819bd6e22b` · investigação `inv_0077c0f60aa15fa431b0` (versão 1) · estado: **complete** · ii_ce/0.1.0
> Verificação: **sustentada** · **aparece no quadro (movimento não comprovado)** · **dita, não vista** · **hipótese** · **contradição em aberto** · **não verificada**. Concordância entre especialistas não eleva o estado.

Como o vídeo PODE ter sido feito. Só o que está marcado **observada**/**comprovada** é fato; o restante é hipótese ou informação ausente.

| classe | item | estado | detalhe | evidências |
|---|---|---|---|---|
| Técnica observada | legenda_sobreposta | contradição em aberto | nível 'observed_in_frame': a técnica aparece no quadro. Não prova: como ela surge, quanto dura ou se é animada. | [ev:e37f6f94] |
| Hipótese | legenda_sobreposta | hipótese | Hipótese de produção: texto sobreposto à imagem (legenda gravada ou camada de texto). Operações prováveis: definir o texto e a divisão em linhas; criar camada de texto; posicionar dentro da área segura vertical; sincronizar com a fala. | [ev:e37f6f94] |
| Ferramenta sugerida | editor de vídeo com camada de texto | hipótese | Sugestão genérica de categoria de ferramenta; software específico NÃO confirmado. | _sem evidência_ |
| Informação ausente | legenda_sobreposta | — | Não consta nas evidências: fonte, tamanho e contorno; se é gerada automaticamente ou manual. | _sem evidência_ |
| Técnica observada | punch_in | aparece no quadro (movimento não comprovado) | nível 'frame_pair_difference': houve mudança entre dois instantes. Não prova: a trajetória, a curva de movimento ou se houve animação contínua. | [ev:957197b6] |
| Hipótese | punch_in | hipótese | Hipótese de produção: aumento de escala (zoom digital) para dar ênfase. Operações prováveis: duplicar o trecho ou aplicar keyframe de escala; recortar o enquadramento; alinhar ao ponto de ênfase da fala. Movimento NÃO comprovado por quadros. | [ev:957197b6] |
| Ferramenta sugerida | qualquer editor com escala/keyframe | hipótese | Sugestão genérica de categoria de ferramenta; software específico NÃO confirmado. | _sem evidência_ |
| Informação ausente | punch_in | — | Não consta nas evidências: percentual de escala; se foi corte seco ou animado. | _sem evidência_ |
| Técnica observada | split_screen | sustentada | nível 'observed_in_frame': a técnica aparece no quadro. Não prova: como ela surge, quanto dura ou se é animada. | [ev:51268193] |
| Hipótese | split_screen | hipótese | Hipótese de produção: dois ou mais elementos lado a lado no quadro. Operações prováveis: definir a grade; posicionar camadas; alinhar duração e áudio. | [ev:51268193] |
| Ferramenta sugerida | editor com camadas | hipótese | Sugestão genérica de categoria de ferramenta; software específico NÃO confirmado. | _sem evidência_ |
| Informação ausente | split_screen | — | Não consta nas evidências: proporção da divisão. | _sem evidência_ |
| Ferramenta comprovada | CapCut | sustentada | nome ou interface legível no vídeo | [ev:a5a2ccf2] |
| Ferramenta mencionada | n8n | dita, não vista | citada em fala/legenda (metadata_only); uso no vídeo NÃO demonstrado | [ev:f4a654a9] |
