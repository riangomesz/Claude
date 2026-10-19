# Handoff para o Antigravity — Creative Engine (MS06)

Branch `claude/instagram-intelligence-creative-engine-06` (a partir de `claude/instagram-intelligence-backend-supreme-04` @ `dac131f`). Pasta `proposals/creative_engine_v1/`. **Nada foi executado no Windows, no n8n real, nem com mídia privada.**

## 1. Receber a branch (PowerShell, no clone da nuvem — NÃO no Projeto-MVP)

```powershell
git fetch origin claude/instagram-intelligence-creative-engine-06
git checkout claude/instagram-intelligence-creative-engine-06
cd proposals\creative_engine_v1
```

## 2. Validar isolado (sem tocar em banco real)

```powershell
python -X utf8 run_tests.py                         # esperado: 44 testes OK
python -X utf8 -m ii_ce.demo --out $env:TEMP\ce_demo  # esperado: 13/13 verificações
cd ..\backend_engine_v1; python -X utf8 run_tests.py  # esperado: 94 testes OK (backend intacto)
```
Se algo falhar no Windows e passar na nuvem, anote: é provável portabilidade (caminhos, encoding, `PermissionError` em `os.replace`). Reporte o traceback, não altere o backend.

## 3. Conectar artefatos existentes do pipeline (somente CÓPIA)

O motor lê o banco e a raiz de artefatos do `ii_be` (`be_artifacts`, análise corrente do `ii_mm`). Copie o `engine.sqlite` e a pasta `store/` do piloto para uma pasta de teste e rode, na cópia:

```powershell
python -X utf8 -m ii_ce.serve --db C:\teste\engine.sqlite --root C:\teste\store --out C:\teste\dossies --staging C:\teste\obsidian_staging --port 8777
```
A primeira execução **acrescenta** tabelas `ce_*` ao arquivo (aditivo; faça backup antes). Os especialistas continuam MOCK.

## 4. Testar com o piloto real `DQV5dm6gCvH`

Bloqueado aqui: o vídeo e os artefatos não existem neste ambiente. No Windows: ingerir o piloto no `ii_be`, deixar o pipeline gerar a análise corrente, descobrir o `reference_id` (`list_references` da API do `ii_be`), então:

```powershell
curl -X POST http://127.0.0.1:8777/v1/open_investigation -H "Content-Type: application/json" -d '{"reference_id":"ref_...","depth":"deep","requested_by":"human:rian"}'
curl -X POST http://127.0.0.1:8777/v1/run_investigation -H "Content-Type: application/json" -d '{"investigation_id":"inv_..."}'
curl -X POST http://127.0.0.1:8777/v1/generate_dossier -H "Content-Type: application/json" -d '{"investigation_id":"inv_..."}'
```
**O que verificar no dossiê real:** (a) as chaves de afirmação batem com o que a análise tem (hoje o mock só estrutura evidências; um modelo real pode usar outras chaves, ver §6); (b) nenhum texto da legenda/transcrição aparece como instrução; (c) seções "Sem dados" são verdadeiras; (d) os roteiros e adaptações são claramente "PROPOSTA".

## 5. Importar o workflow n8n (desativado)

Ver `n8n/README.md`. Importe em um n8n **de teste**, não ative, rode "Teste manual" com um `reference_id` da cópia. Se um nó pedir upgrade de versão, anote qual.

## 6. Conectar provedores reais, um por vez (somente com aprovação do usuário)

1. Implemente `SpecialistProvider.call(instructions, data, request, cancel)` e devolva `ii.ce.specialist_result.v1` (veja `MockSpecialist` e `contracts.sanitize_result`).
2. **Chaves canônicas:** o provedor precisa usar `tecnica:<nome>`, `ferramenta:<nome>`, `cena:<t>`, `narrativa:<…>`, `passo:NN`, `producao:<técnica>`, senão a reconciliação não agrupa. Adicione um normalizador no adaptador se o modelo devolver texto livre.
3. `requires_approval`/`estimate_usd` > 0 faz a tarefa esperar `approve(…, 'paid_models', …)` por uma pessoa.
4. Registre em `CreativeEngine(providers={...})`. `network=True` é recusado hoje: para liberar rede, mude `SpecialistGateway` **com autorização explícita**, em outra missão.
5. Ordem sugerida: audiovisual → reprodução → criativo → implementação; compare cada saída com o dossiê MOCK antes do próximo.

## 7. Exibir no painel (sem alterar o painel nesta missão)

Leituras prontas: `get_status` (progresso, conflitos, `awaiting_human`, `pending_approvals`), `get_investigation` (objeto completo), `list_open_questions`. Escritas humanas: `approve`, `register_review`. O Codex integra a interface; este pacote não toca frontend.

## 8. Integração gradual, mediante aprovação

(1) cópia do banco + API local; (2) workflow até "Gerar dossiê"; (3) staging do Obsidian; (4) eventos; (5) um provedor real; (6) painel. Cada passo é reversível: desligar a API e apagar `ce_*` não afeta `be_*` nem `ii_mm`.

## Limites a lembrar

Não executar modelos pagos, não gravar no Vault real, não publicar mídia, não alterar o Projeto-MVP, não mexer em workflows n8n existentes.
