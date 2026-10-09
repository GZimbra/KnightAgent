# Código e IA local no GitHub

O código está no repositório. A Release de código e IA contém partes de até 1,8 GiB com `runtime/ollama/`, `runtime/models/` e [a licença Ollama](licenses/OLLAMA-LICENSE.txt); **não contém `KnightAgent.exe` nem `KnightAgentCopilot.exe`**. O arquivo `knightagent-local-ai.json` registra o tamanho e SHA-256 de cada parte e arquivo. Baixe o JSON e todas as partes da mesma Release para a pasta `dist/local-ai`.

## Instalar no Windows

```powershell
git clone https://github.com/GZimbra/KnightAgent.git
cd KnightAgent
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe .\scripts\package-local-ai.py restore --package .\dist\local-ai --root .
Copy-Item .\config.example.yaml .\config.yaml
```

Execute o firewall uma vez em PowerShell **como Administrador**:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure-offline-firewall.ps1
```

Depois, em PowerShell comum:

```powershell
.\.venv\Scripts\knightagent.exe --config .\config.yaml test-connection
.\.venv\Scripts\python.exe -m knightagent.gui.main --config .\config.yaml
```

O comando `restore` confere os hashes antes de gravar e confirma os blobs pelos digests dos manifests Ollama. A aplicação inicia seu processo Ollama privado, somente em loopback, com cloud desativado; o firewall bloqueia saída externa. O `config.yaml`, conversas, memória e biblioteca são criados localmente e não fazem parte da Release.

## Gerar as partes a partir da instalação local

```powershell
.\.venv\Scripts\python.exe .\scripts\package-local-ai.py pack --root . --package .\dist\local-ai
```

A pasta de saída deve estar vazia. O empacotador aceita somente os manifests de `qwen2.5:7b` e `knightagent-automation:latest`, seus blobs verificados e os arquivos de `runtime/ollama/`. Não empacota sessões, bases de dados, configurações privadas nem os executáveis KnightAgent.

O [Qwen2.5 7B](https://ollama.com/library/qwen2.5%3A7b) usa Apache 2.0. O núcleo [Ollama](https://github.com/ollama/ollama/blob/main/LICENSE) usa MIT; os avisos de terceiros incluídos na distribuição do runtime devem acompanhar os respectivos arquivos.
