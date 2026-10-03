# Login e auxílio do Copilot

O KnightAgent mantém uma única interface. Quando o usuário habilita o complemento, o orquestrador envia o pedido atual ao Microsoft 365 Copilot, recebe uma referência e a entrega ao Ollama. O Ollama continua local e é responsável pelo planejamento, edição e revisão. O login acontece uma vez na página oficial Microsoft; as consultas seguintes ocorrem em segundo plano.

## Preparação única pela organização

A integração utiliza a Microsoft 365 Copilot Chat API em preview (`/beta`). A Microsoft exige uma conta de trabalho/escola com a licença adicional Microsoft 365 Copilot. Conta Microsoft pessoal e apenas a instalação do aplicativo Copilot não dão acesso. A Microsoft também informa que APIs beta não têm suporte para aplicações em produção. [Licenciamento e capacidades](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview), [contas e permissões da API](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations).

O responsável pelo Microsoft Entra deve:

1. Registrar um aplicativo cliente público para o KnightAgent, adequado ao tenant da empresa. Em **Authentication → Add a platform**, selecionar **Mobile and desktop applications** e configurar o URI de redirecionamento `http://localhost`. O login usa o navegador do sistema e retorna ao aplicativo por loopback. Não criar segredo de cliente. [Autenticação interativa MSAL Python](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens).
2. Autorizar as permissões delegadas Microsoft Graph exigidas pela Chat API: `Sites.Read.All`, `Mail.Read`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, `Chat.Read`, `ChannelMessage.Read.All` e `ExternalItem.Read.All`. O consentimento deve seguir as políticas da organização. Essas permissões permitem à API fundamentar respostas nos dados corporativos aos quais o usuário já possui acesso.
3. Em **Configurações → Copilot → Configuração da organização**, marcar **Mostrar configuração da TI**, preencher **ID do aplicativo (client ID)** e **Organização (tenant)** e clicar em **Salvar configurações**. Esses identificadores públicos podem acompanhar a configuração distribuída pela TI; tokens de usuário não devem ser copiados entre máquinas.
4. Confirmar que os usuários têm a licença necessária e que a política de acesso da empresa permite autenticação e uso da API.

O campo tenant aceita o identificador da organização ou `organizations`, para contas de trabalho/escola. Um aplicativo de tenant único deve usar o diretório correspondente. `organizations` não transforma um registro de tenant único em um aplicativo de várias organizações; outras organizações precisam de registro/consentimento compatível.

Exemplo de configuração sem credenciais:

```toml
[complementary]
copilot = false
mode = "account"
client_id = "00000000-0000-0000-0000-000000000000"
tenant = "organizations"
```

Substitua o ID ilustrativo pelo registro real. Deixe o complemento desativado até configurar o ambiente de trabalho.

## Uso por cada pessoa

1. Abra **Configurações → Copilot**.
2. Clique em **Entrar com conta Microsoft** e conclua o login e o consentimento na página oficial Microsoft. Não informe senha no KnightAgent.
3. Use **Verificar acesso** para confirmar que a conta pode consultar a API. O login concluído, isoladamente, não comprova licença nem autorização para o Copilot.
4. Marque **Ativar auxílio automático do Copilot** e clique em **Salvar configurações**. O login sozinho não ativa o envio de pedidos. Depois, faça o pedido na conversa normal. Não precisa abrir o Copilot, copiar respostas nem acompanhar outra janela.
5. Use **Trocar conta** para conectar outra pessoa ou **Desconectar** para remover a sessão local. Desconectar o KnightAgent não altera sessões abertas em outros aplicativos Microsoft.

## Limite entre o local e o online

- `KnightAgent.exe` e o Ollama privado mantêm o bloqueio de internet. O auxiliar `KnightAgentCopilot.exe` realiza autenticação e chamadas Microsoft separadamente.
- A consulta contém uma instrução fixa de auxílio e até 4.000 caracteres do pedido atual. Se o usuário incluir informação sensível nesse texto, ela fará parte da consulta online. Arquivos, histórico, memória e biblioteca não são anexados automaticamente.
- A resposta do Copilot é limitada a 6.000 caracteres e entra como referência não confiável. O orçamento de contexto pode reduzi-la ainda mais. Ela não autoriza escrita, não executa código e não substitui a aprovação do diff.
- Tokens persistidos são protegidos por DPAPI para o usuário do Windows e ficam separados das configurações. O aplicativo não salva senhas nem acrescenta tokens às conversas.
- Falha de login, licença, consentimento ou rede gera aviso; o pedido continua com a IA local. A opção desativada não consulta o Copilot.

## Diagnóstico

| Situação | Ação |
| --- | --- |
| Falta ID do aplicativo | Solicitar à TI o registro Entra e preencher Configuração da organização. |
| Login concluiu, mas não há acesso | Conferir licença Microsoft 365 Copilot, permissões delegadas e consentimento do tenant. |
| Conta pessoal/Premium não é aceita | Usar a conta de trabalho/escola que atende aos requisitos da Chat API. |
| Política de acesso bloqueia o login | Encaminhar a mensagem exibida à TI para revisar o método de autenticação permitido. |
| Auxiliar ausente no pacote | Reconstruir o pacote completo, incluindo KnightAgentCopilot.exe. |
| Rede Microsoft indisponível | Manter o trabalho local e tentar verificar o acesso posteriormente. |

Os testes locais usam respostas simuladas para validar autenticação, limites de dados e cooperação. Não foi conectado neste computador um usuário corporativo licenciado; o funcionamento real da conta e as políticas da empresa precisam ser verificados com **Verificar acesso** no ambiente autorizado.
