# Benchmark local

Execute na raiz do repositório após configurar o firewall offline do Ollama:

```powershell
.\.venv\Scripts\python.exe -m knightagent.benchmark.runner --suite benchmarks/suite.yaml --config config.yaml --output benchmarks/runs/candidate.json
.\.venv\Scripts\python.exe -m knightagent.benchmark.compare benchmarks/baselines/baseline-v2.json benchmarks/runs/candidate.json
```

O runner recusa sobrescrever relatórios. A suíte, as tarefas, o número de repetições, a seed e os limites do sandbox são arquivos de dados. Acrescente uma tarefa JSON com `split`, `language`, `operation`, `prompt` e `checks`; para medir o agente, acrescente `agent.prompt` e `agent.target_path`. O hold-out fica exclusivamente nesses arquivos de avaliação: o runner desliga memória, RAG e referências externas no modo agente. Nenhum prompt ou exemplo do hold-out entra no desenvolvimento.

O modo `raw` envia somente a mensagem de usuário e uma seed ao Ollama. Assim, o SYSTEM e os parâmetros de cada Modelfile são aplicados. O modo `agent` usa o loop atual de planejador, executor com ferramentas e aprovação simulada de gravação, e revisor. Seus arquivos ficam em diretórios temporários. Os dois modos registram os mesmos campos de métricas do Ollama; no agente, são somados em todas as chamadas.

Funções Python são executadas num processo Linux em WSL dentro de um chroot temporário, com novos namespaces de rede, montagem e PID, `/usr` montado somente para leitura, UID sem privilégios, ambiente limpo e limites de CPU, memória, arquivo, processo e tempo. A proteção é do sistema operacional; imports não são usados como barreira. Se WSL ou as primitivas de isolamento faltarem, a execução recebe `skipped`. O benchmark requer WSL com distribuição configurada em `suite.yaml` e `unshare`, `chroot`, `prlimit` e `timeout` disponíveis.

VBA recebe validação estática de estrutura e requisitos do caso. Excel/COM é `skipped` quando indisponível. Office Scripts recebe validação estática de assinatura, delimitadores e chamadas exigidas; a compilação completa requer declarações `ExcelScript` e fica `skipped` quando ausente. VB.NET recebe verificação estática e compilação opcional com .NET SDK. Os checks estáticos detectam erros estruturais, mas não provam comportamento no Office. `passed/evaluated` exclui tarefas integralmente puladas; `coverage` mostra a fração efetivamente avaliada. Checks opcionais pulados são registrados separadamente em cada execução.

Cada repetição usa seed determinística. As variâncias são populacionais. JSON e Markdown preservam hashes da suíte e tarefas, parâmetros efetivos por modo, métricas nativas de tempo/tokens e hash da resposta, sem guardar o código gerado. Relatórios só são diretamente comparáveis quando versão, hash da suíte, hashes das tarefas e N coincidem.
