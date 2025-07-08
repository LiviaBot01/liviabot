# 🤖 LiviaBot

**Assistente de IA inteligente para Slack da agência Live**

A LiviaBot é uma assistente de IA que responde mensagens diretas, canais e threads no Slack quando mencionada. Ela utiliza o modelo o3-mini da OpenAI para fornecer respostas inteligentes e contextualizadas.

## ✨ Funcionalidades

- 💬 **Resposta automática em DMs**: Responde todas as mensagens diretas
- 🏷️ **Resposta por menção**: Responde quando mencionada em canais (`@LiviaBot`)
- 🧵 **Suporte a threads**: Mantém contexto em conversas em thread
- 📊 **Registro de uso**: Salva logs de interações em CSV
- ⏳ **Indicador de carregamento**: Mostra "Aguarde..." enquanto processa
- 🎯 **Personalidade customizada**: Assistente inteligente, bem-humorada e sagaz

## 🚀 Instalação e Configuração

### Pré-requisitos

- Python 3.8 ou superior
- Git
- Conta no Slack com permissões de administrador
- Conta na OpenAI com acesso à API

### Passo 1: Clone o repositório

```bash
git clone https://github.com/LiviaBot01/liviabot.git
cd liviabot
```

### Passo 2: Instale as dependências

```bash
pip install -r requirements.txt
```

### Passo 3: Configure as variáveis de ambiente

```bash
export SLACK_BOT_TOKEN="xoxb..."
export SLACK_APP_TOKEN="xapp..."
export OPENAI_API_KEY="sk..."
```

### Passo 4: Executar a LiviaBot

```bash
python Livia.py
```

Se tudo estiver configurado corretamente, você verá:

```
🤖 Livia está iniciando...
✅ Conectada ao Slack!
⚡️ Bolt app is running!
```

## 📝 Como Usar

### Mensagens Diretas
Envie qualquer mensagem diretamente para a LiviaBot no Slack.

### Canais
Mencione a bot em qualquer canal: `@LiviaBot sua pergunta aqui`

### Threads
Se você mencionar a bot na primeira mensagem de uma thread, ela responderá a todas as mensagens subsequentes nessa thread.

## 📊 Logs e Monitoramento

- **Console**: Logs em tempo real das mensagens recebidas e enviadas
- **CSV**: Arquivo `registro_uso.csv` com histórico de todas as interações

## 🛠️ Estrutura do Projeto

```
Livia/
├── Livia.py              # Código principal da bot
├── requirements.txt      # Dependências Python
├── registro_uso.csv     # Log de uso 
└── README.md           # Este arquivo
```

## 🐛 Solução de Problemas

### Slack
- ✅ Verifique se as chaves de API foram exportadas corretamente

### OpenAI
- ✅ Verifique o [Changelog](https://platform.openai.com/docs/changelog) da OpenAI 
- ✅ Verifique se sua chave de API está válida
- ✅ Confirme se você tem [créditos disponíveis](https://api.slack.com/apps)

### Slack APPs
- ✅ Reinstale o app no [workspace](https://api.slack.com/apps) se necessário 

---

## 📄 Licença

Este projeto é propriedade da agência Live.
Desenvolvido com 💛 por Lucas Vieira



