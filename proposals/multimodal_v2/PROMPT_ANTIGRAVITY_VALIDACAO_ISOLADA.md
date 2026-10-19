# Prompt para o Antigravity: validação isolada da RC `ii_mm-1.0.0-rc1`

Copie o bloco abaixo inteiro para o agente do Antigravity IDE. Ajuste só as três linhas marcadas com `<<AJUSTE>>`.

---

```text
MISSÃO: VALIDAÇÃO ISOLADA DA RELEASE CANDIDATE ii_mm-1.0.0-rc1 (Estágios 1 e 2)

Você é o agente local responsável pelo Projeto-MVP (Instagram Intelligence) nesta máquina Windows. Você
continua dono de todas as alterações locais: nada desta missão autoriza mudar o projeto. O objetivo é
receber um pacote produzido na nuvem, provar que ele está íntegro, testá-lo isolado, compará-lo com o
código local e, só depois disso, rodar o modo sombra. Entregue um relatório de compatibilidade.

DADOS DA RC (publicados fora do pacote; não os altere)
- Repositório/branch: https://github.com/riangomesz/Claude.git, branch claude/instagram-intelligence-audit-4ezsd1
- Commit do código: d0e1916099bc945a7e8478a4d14b55c919ce4c40
- SHA-256 do manifesto: 10f0e9d88afaa435f5ad1e4899bcb6b942fff812f9831554c34671898e75e209
- Projeto-MVP local (SOMENTE LEITURA): <<AJUSTE: C:\caminho\do\Projeto-MVP>>
- Catálogo (SOMENTE LEITURA): <<AJUSTE: C:\caminho\do\Projeto-MVP\storage\catalog.sqlite>>
- Pasta raiz NOVA para esta missão (fora do projeto, caminho curto): <<AJUSTE: C:\ii_rc>>

REGRAS ABSOLUTAS
1. Preserve execuções em andamento. Antes de começar, liste o que está rodando (servidor do painel,
   n8n, importações, transcrições). Não pare, não reinicie e não "libere" nenhum processo. Se o catálogo
   estiver em uso intenso (importação em massa), adie a etapa Sombra.
2. Não sobrescreva código. Não copie nenhum arquivo do pacote para dentro do Projeto-MVP. Não aplique
   patches. Não rode `git checkout`, `git reset`, `git stash`, `git clean` nem `pip install` no Projeto-MVP.
3. Não interrompa nem reconfigure serviços: n8n, Ollama, ii-bridge, extensão de captura, painel, Obsidian.
4. Trabalhe só na pasta raiz nova. Pasta de trabalho: <raiz>\trabalho (criada e apagada pelo script).
5. Não abra o catálogo para escrita. A etapa Sombra copia por snapshot (origem em mode=ro); não use outra
   ferramenta para abrir o catálogo.
6. Não edite o pacote recebido. Se algo falhar, registre a saída completa e devolva; não "conserte".
7. Não integre nada em produção. O Estágio 3 exige decisão humana escrita (CRITERIOS_ADOCAO.md, C10)
   e você não pode autorizá-lo.
8. Não envie para fora desta máquina: bancos, mídia, .env, tokens, credenciais, .n8n-files.
9. Use somente comandos de proposals\multimodal_v2\GUIA_WINDOWS_POWERSHELL.md e do script
   handoff\windows\ii_rc.ps1. Nada de remoção ampla; a única remoção é -Etapa Limpar (exige o marcador).

PASSOS (pare no primeiro que falhar e vá para RELATÓRIO)
A. Estado inicial do projeto (só leitura): em <projeto>, `git rev-parse HEAD` e `git status --short`;
   guarde as duas saídas. Anote `$PSVersionTable.PSVersion` e o Python disponível (`py -3 --version`).
B. Obter o código: crie <raiz> (New-Item; se já existir, PARE e peça outra pasta), clone a branch em
   <raiz>\repo e confira `git -C <raiz>\repo log --oneline -1`. Pacote = <raiz>\repo\proposals\multimodal_v2.
C. Integridade (antes de executar qualquer código do pacote):
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File <pacote>\handoff\windows\ii_rc.ps1 -Etapa Conferir -PacoteDir <pacote> -ManifestoSha256 10f0e9d88afaa435f5ad1e4899bcb6b942fff812f9831554c34671898e75e209
   Esperado: "OK: pacote íntegro e ambiente compatível". Guarde as linhas "RC:" e "Python ... SQLite ...".
D. Preparar e testar (mesmo script, mesmos -PacoteDir; acrescente -TrabalhoDir <raiz>\trabalho -ProjetoMvp <projeto>):
   -Etapa Preparar, depois -Etapa Testes. Esperado: "OK (skipped=13)" sem o projeto e "OK" com ele, 384 testes.
   Os testes copiam core/, config/ e temporal_intelligence/ para uma pasta temporária; o projeto não é tocado.
E. Compatibilidade: -Etapa Compatibilidade. Leia <raiz>\trabalho\relatorio_compatibilidade.json. Para cada
   item alterado/ausente/novo, diga o que mudou no código local desde c6845a4 e se afeta o adaptador
   correspondente (MATRIZ_COMPATIBILIDADE.md). Confira também, só lendo: os valores reais de `tipo` em
   revisao_visual_fase5.json contra ii_mm/legacy.py FICHA_TIPO_TO_TAG, e os valores distintos de
   editorial_category_source no snapshot (não no catálogo vivo).
F. Somente se C, D e E estiverem OK ou com diferenças analisadas: -Etapa Sombra -CatalogoDb <catálogo> -Limite 200.
   Anote o hash do catálogo antes e depois (Get-FileHash) e se houve outra escrita no período.
   Não revise as divergências por conta própria: entregue o CSV para o curador humano.
G. Confirme que o projeto não mudou: repita `git rev-parse HEAD` e `git status --short` e compare com A.
   Rode -Etapa Conferir de novo (o pacote não pode ter arquivos novos).
H. Não rode -Etapa Limpar antes de copiar os relatórios para a entrega.

RELATÓRIO DE COMPATIBILIDADE (entregue em Markdown, sem dados privados)
1. Ambiente: Windows, PowerShell (5.1 ou 7), Python, SQLite (da linha do validador).
2. Integridade: resultado da etapa C (saída completa se falhou).
3. Testes: as duas últimas linhas de cada log, e o trecho completo de cada falha ou erro.
4. Compatibilidade: tabela item | baseline c6845a4 | local | impacto | ação sugerida.
5. Sombra: campo "totals" de relatorio_sombra.json, tempo do snapshot, hash do catálogo antes/depois.
6. Estado do projeto: saídas de A e G (devem ser idênticas).
7. Itens do CHECKLIST_ACEITE_RC.md (Estágios 1 e 2) marcados, com a evidência de cada um.
8. Problemas do Windows encontrados (travas de arquivo, encoding, caminhos), com o comando que os causou.
9. O que você NÃO fez e por quê (por exemplo, Sombra adiada por importação em andamento).

Ao final, não integre nada. Pergunte ao responsável humano se deseja seguir com a avaliação humana
(AVALIACAO_HUMANA.md) ou devolver o relatório ao Claude Cloud. A limpeza (-Etapa Limpar) só depois da
entrega e com confirmação humana.
```

---

## Notas para quem cola o prompt

- O agente nunca recebe credenciais por este prompt e não precisa delas: o clone da branch é a única operação de rede.
- Se o repositório for privado, o `git clone` usa a autenticação do Git já configurada na máquina. Se não houver, faça o clone manualmente e informe a pasta ao agente.
- Os critérios de "OK" acima valem para o commit `d0e1916`. Uma RC futura (`rc2`) vem com novo hash e novo prompt.
