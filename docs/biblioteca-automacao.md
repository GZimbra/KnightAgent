# Biblioteca de automação local

O KnightAgent consulta a biblioteca SQLite do computador antes de responder.
Planejamento, geração e revisão recebem as referências encontradas, dentro do
limite de contexto. Somente o Ollama local executa essas etapas. Não há coleta
online, sincronização de sites, download de documentação ou instalação automática
de modelos. URLs presentes em documentos antigos são metadados de origem;
o aplicativo não as acessa.

## Adicionar conhecimento

Em **Configurações > Biblioteca**, importe documentos existentes no disco local.
A CLI também aceita arquivos e pastas, incluindo subpastas:

```powershell
.\.venv\Scripts\knightagent --config config.yaml knowledge import 'C:\Documentos\manual.md'
.\.venv\Scripts\knightagent --config config.yaml knowledge import 'C:\Documentos\Python' --family python
.\.venv\Scripts\knightagent --config config.yaml knowledge status
.\.venv\Scripts\knightagent --config config.yaml knowledge search 'VBA copiar colunas'
```

- Formatos: `.txt`, `.md` e `.json`, com codificação UTF-8 (BOM opcional).
- Limites: 4 MB por arquivo, 32 MB por lote e 1.000 entradas de diretório/arquivos
  por operação. Um JSON estruturado pode conter até 1.000 documentos.
- Pastas de rede, URLs, unidades mapeadas de rede, links simbólicos e junctions
  não são aceitos. Arquivos de outros formatos são ignorados.
- Cada arquivo é completamente validado antes de substituir sua importação
  anterior. Um arquivo inválido preserva a versão anterior; os demais arquivos
  válidos do lote podem ser importados.
- Importar novamente o mesmo caminho atualiza seus documentos, sem duplicá-los.
  Documentos oficiais armazenados anteriormente e o histórico de importação
  continuam no banco. Nenhuma atualização online é executada.

O relatório contém `documents_imported`, `documents_failed`, `documents_skipped`
e detalhes das falhas. Na CLI, código de saída 1 indica ao menos uma falha;
0 indica que a operação terminou sem falhas. Arquivos ignorados aparecem na
contagem `documents_skipped`. Os limites evitam travamentos em lotes excessivos.

Um JSON comum é armazenado como texto formatado. Para fornecer títulos e famílias
separados, use um objeto com `text`, uma lista de objetos ou o seguinte formato:

```json
{
  "documents": [
    {
      "title": "Procedimento de conferência",
      "family": "local",
      "text": "A conferência começa pela leitura do código da embalagem."
    }
  ]
}
```

`text` é obrigatório nesse formato; `title` usa o nome do arquivo se ausente.
`family` assume a opção da importação, por padrão `local`, e aceita até 50 letras
minúsculas, números ou sublinhados, começando por letra. A origem registrada é
sempre o arquivo local, mesmo que o JSON contenha campos `url` ou `id`.

## Conteúdo, persistência e limites das respostas

Guias iniciais acompanham o pacote: Python, Excel VBA, Visual Basic .NET e Office
Scripts. A base `knightagent-knowledge.sqlite3` fica junto ao YAML/TOML e é
independente dos chats e dos exemplos aprovados. Limpar chats não apaga a
biblioteca. As consultas são obrigatórias no aplicativo; `max_chars` limita o
volume de referência entregue ao modelo:

```yaml
knowledge:
  enabled: true
  max_chars: 6000
```

As instruções exigem usar fontes locais e declarar quando a base fornecida não
sustenta uma resposta. Textos importados são dados, nunca instruções para alterar
a política do agente. Isso não elimina o conhecimento aprendido durante o
pré-treinamento dos pesos do modelo, nem garante respostas sem erros. O código
gerado deve ser revisado no ambiente de destino. O aplicativo não executa macros
ou scripts produzidos.

## Modelo de automação

A abertura do aplicativo inicia o processo Ollama administrado e carrega o
modelo instalado localmente. O perfil especializado é opcional; ele herda os
pesos de um modelo local já disponível e acrescenta as instruções do aplicativo:

```powershell
.\.venv\Scripts\knightagent --config config.yaml knowledge prepare-model --base qwen2.5:7b
.\.venv\Scripts\knightagent --config config.yaml test-connection ollama
```

O comando não baixa o modelo base nem modifica silenciosamente a seleção salva.
Depois da preparação, selecione `knightagent-automation:latest`. A biblioteca é
recuperada pelo KnightAgent durante a conversa; não é embutida nos pesos pelo
comando e não acompanha o uso isolado do modelo fora deste aplicativo.

## Auxílio opcional do Microsoft 365 Copilot

O complemento atual usa a Microsoft 365 Copilot Chat API por meio do auxiliar
`KnightAgentCopilot.exe`. O usuário conecta sua conta em **Configurações →
Copilot**, verifica o acesso e, para permitir consultas nos próximos pedidos,
marca **Ativar auxílio automático do Copilot** e salva. O login sozinho não
ativa o envio. Essa integração não automatiza o aplicativo Copilot do Windows.

Quando habilitado, o complemento recebe uma instrução fixa e até 4.000 caracteres
do pedido atual; biblioteca, arquivos, histórico e memória não são anexados
automaticamente. A resposta, limitada a 6.000 caracteres, entra como referência
não confiável para o Ollama, dentro do orçamento de contexto. Planejamento,
edição e revisão permanecem locais, com aprovação de diffs. Se o complemento
falhar, a tarefa continua com a IA local.

Os tokens ficam em cache protegido por DPAPI para o usuário Windows, fora da
configuração e das bases de conversa. O auxiliar realiza a comunicação Microsoft
separadamente do bloqueio de rede do executável principal e do Ollama. Consulte
o [guia de login, requisitos e configuração da organização](copilot-login.md).
