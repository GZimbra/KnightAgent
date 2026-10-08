# Etapa 2.1 — validação antes de salvar (candidata rejeitada)

Comparação com `baseline-v2-n5.json`: mesmos hashes de suite e tarefas, mesmos seeds, 5 repetições, 230/230 execuções avaliadas e 0 skipped em ambos. Os 180 outputs do modo cru têm hashes idênticos.

| Modelo | Modo | Conjunto | Baseline | Candidata | Tempo médio antes/depois (s) | Tokens gerados médios antes/depois |
|---|---|---|---:|---:|---:|---:|
| qwen2.5:7b | cru | desenvolvimento | 22/30 | 22/30 | 7,1 / 6,8 | 124,5 / 124,5 |
| qwen2.5:7b | agente | desenvolvimento | 2/15 | 6/15 | 50,0 / 62,2 | 843,1 / 977,7 |
| qwen2.5:7b | cru | hold-out | 36/60 | 36/60 | 9,2 / 8,8 | 164,9 / 164,9 |
| qwen2.5:7b | agente | hold-out | 9/10 | 6/10 | 55,2 / 52,3 | 913,5 / 818,3 |
| knightagent-automation:latest | cru | desenvolvimento | 24/30 | 24/30 | 17,6 / 17,0 | 184,4 / 184,4 |
| knightagent-automation:latest | agente | desenvolvimento | 5/15 | 7/15 | 60,3 / 76,0 | 831,7 / 1067,6 |
| knightagent-automation:latest | cru | hold-out | 33/60 | 33/60 | 15,4 / 14,7 | 216,8 / 216,8 |
| knightagent-automation:latest | agente | hold-out | 8/10 | 9/10 | 77,2 / 66,9 | 997,8 / 951,9 |

Total: **139/230 → 143/230** (+4). Critério de aceitação: ganho agregado estritamente positivo, cobertura preservada e nenhuma regressão individual no hold-out. **Reprovada**: `qwen2.5:7b`, modo agente, `python-edit-join`: **5/5 → 2/5**. Nas cinco execuções candidatas dessa tarefa a verificação pré-salvamento passou; o problema é funcional e não foi detectado pela checagem de sintaxe.

A candidata executou 44 validações aprovadas e 13 tentativas de escrita rejeitadas pelo validador. Não havia arquivos de testes autocontidos no workspace temporário das tarefas do agente; `ruff` não estava disponível no sandbox. Portanto, a candidata mediu principalmente sintaxe Python e estrutura estática. Todos os cinco campos de métricas nativas do Ollama foram registrados em cada execução; `model_errors` está vazio.

**Decisão:** alteração do loop de edição revertida. Os relatórios completos e o baseline N=5 permanecem como evidência. Nenhum commit foi criado.
