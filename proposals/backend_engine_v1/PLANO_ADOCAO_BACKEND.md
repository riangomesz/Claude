# Plano de adoção incremental do backend `ii_be`

O Instagram Intelligence continua funcionando durante todos os estágios: nenhum estágio desliga ou substitui o pipeline atual sem decisão explícita. **Nenhum estágio de produção é autorizado por este plano.** Cada estágio exige o anterior concluído e registrado.

## Estágio 1: testes isolados no Windows

- **Pré-requisito:** RC1 validada no Windows (Missão 03, Estágio 1).
- **O que fazer:** obter a branch numa pasta nova e rodar `run_tests.py`, a demonstração e o benchmark pequeno (`HANDOFF_ANTIGRAVITY_BACKEND.md`, seção 10).
- **Critérios verificáveis:**
  - suíte verde, com o log guardado;
  - resumo da demonstração igual ao da nuvem em todos os campos de `18_verification`;
  - `git status` do Projeto-MVP idêntico antes e depois;
  - nenhum arquivo criado fora da pasta de teste;
  - benchmark registrado.

## Estágio 2: backend experimental com dados sintéticos

- **O que fazer:** rodar o motor numa pasta própria (banco `backend.sqlite`, raiz de artefatos e staging próprios) com fixtures sintéticas e, se desejado, o servidor HTTP local para um protótipo de painel separado.
- **Critérios verificáveis:**
  - simulação de queda e retomada sem duplicação (`jobs_completed_twice = 0`, `stage_results_duplicated = 0`);
  - `integrity_check = ok`;
  - diagnóstico sem bloqueios inexplicados;
  - nenhuma porta exposta além de 127.0.0.1;
  - nenhum evento enviado para fora (só JSONL).

## Estágio 3: modo sombra com o catálogo real (mediante verificação de segurança)

- **Pré-requisito:** o Estágio 2 do modo sombra da RC1 executado com segurança (snapshot, catálogo identificado, sem importação em massa em curso).
- **O que fazer:** escrever e revisar o adaptador "linha de `instagram_items` → `ii.be.ingest.v1`" e ingerir a partir do SNAPSHOT num banco do backend separado. Ferramentas locais registram artefatos para um lote pequeno (até 50 referências).
- **Critérios verificáveis:**
  - hash do catálogo inalterado por causa da missão;
  - decisões humanas legadas importadas somente como curadoria explícita e auditável;
  - divergências exportadas para revisão;
  - tempo de processamento por referência medido no Windows.

## Estágio 4: avaliação humana das divergências

- **O que fazer:** o curador revisa as divergências e a amostra de 30 a 50 vídeos (`proposals/multimodal_v2/AVALIACAO_HUMANA.md`). As correções entram pelo `CurationService`.
- **Critérios verificáveis:**
  - planilhas preenchidas;
  - concordância em contagens;
  - lista de regras a ajustar;
  - decisão escrita sobre quais facetas são úteis no painel.

## Estágio 5: integração de UMA funcionalidade por vez (autorização explícita a cada uma)

Ordem sugerida, da menor para a maior superfície:
1. Fila e retomada para UMA etapa existente: por exemplo, registrar as transcrições já produzidas como artefatos e acompanhar no diagnóstico, sem trocar o pipeline.
2. Consulta: o painel lê a busca e as perguntas de conhecimento pela API local, só leitura.
3. Curadoria pelo backend, mantendo a decisão humana como autoridade.
4. Eventos para um workflow n8n NOVO (os existentes não são editados).

Para cada funcionalidade, são critérios verificáveis:
- autorização escrita;
- plano de reversão ensaiado (apagar o banco do backend não afeta o Projeto-MVP);
- testes do legado e do backend verdes;
- período de observação com critério de reversão.

## Reversão em qualquer estágio

O backend não altera nada do Projeto-MVP. Para desfazer, basta parar os processos do backend e apagar sua pasta: banco, raiz de artefatos e staging. Workflows novos do n8n, se criados, são desativados e apagados.
