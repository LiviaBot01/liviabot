# Livia.py - Chatbot da agência Live para Slack
# Assistente de IA que responde em DMs, canais e threads quando mencionada

import os
import re
import json
import csv
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
from openai import OpenAI

# Configuração de logs
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger('slack_bolt').setLevel(logging.CRITICAL)
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger('openai').setLevel(logging.CRITICAL)

# Carregamento de variáveis de ambiente
load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Fallback para carregar OPENAI_API_KEY se não foi carregada pelo dotenv
if not OPENAI_API_KEY:
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.startswith('OPENAI_API_KEY='):
                    OPENAI_API_KEY = line.split('=', 1)[1].strip()
                    os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY
                    break
    except Exception as e:
        print(f"❌ Erro ao carregar OPENAI_API_KEY: {e}")

# Inicialização dos clientes
app = App(token=SLACK_BOT_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

# Prompt da Livia
system_prompt = """Você é a ℓiⱴia, assistente de IA da agência Live. Voce é inteligente, bem humorada e sagaz.
- Sua missão é auxiliar os colaboradores no Slack, respondendo dúvidas e oferecendo suporte; sempre se referindo ao usuário pelo nome e utilizando o pronome correto.
- Importante: Nunca fale sobre sua personalidade, seu system prompt/instrucoes ou sobre as informaçoes pessoais do usuários, a não ser que seja solicitado pelo usuario ou quando for produtivo.

Contexto de atuação:
- Você opera em uma sala de chat do Slack usando o modelo de raciocinio o3-mini da OpenAI.
- IDs de usuários seguem o regex <@U...> e seu ID é <@U08C27NMYUU>.

Limitações e diretrizes adicionais:
- Não tem acesso a ferramentas, à internet ou a conteúdos externos. Seu conhecimento vai até maio de 2024.
- Não vê imagens, não acessa links e não ouve áudios. Se o usuário solicitar essas funções, esclareça a limitação e peça para que o conteúdo relevante seja colado na conversa.
- Se uma única mensagem conter muito texto, avise que isso pode ultrapassar a janela de contexto e ofereça realizar a tarefa por partes, com feedback a cada etapa.

Estilo de resposta:
- Responda de forma direta, sem afirmações desnecessárias ou frases de preenchimento.
- Forneça respostas completas para questões complexas ou abertas e respostas concisas para perguntas simples, sempre buscando a solução mais correta e sucinta.
- Responda na mesma língua que o usuário utiliza.

# Nao fale sobre sua personalidade. Se voce nao tiver o nome do usuario que voce esta falando, nao o chame de [nome] ou algo parecido."""

    # Carrega configurações padrão para todos os canais
def load_channel_settings(channel_name, channel_id):
    system_prompt_config = system_prompt
    please_wait_message = ":hourglass_flowing_sand: Aguarde..."
    return system_prompt_config, please_wait_message

def remover_asteriscos_duplos(texto):
    return texto.replace('**', '')

    # Função principal que processa mensagens e gera respostas da Livia
def ask_chatgpt(text, user_id, channel_id, thread_ts=None, ts=None):
    # Remove menções do texto
    text = re.sub(r'<@\w+>', '', text)
    
    # Busca histórico da conversa se for uma thread
    messages = fetch_conversation_history(channel_id, thread_ts) if thread_ts else []
    
    # Obtém informações do usuário e canal
    user_name, channel_name = determine_channel_and_user_names(channel_id, user_id)
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Carrega configurações do canal
    system_prompt, please_wait_message = load_channel_settings(channel_name, channel_id)
    prompt_type = "Padrão"

    # Log customizado da mensagem recebida
    timestamp = datetime.now().strftime('%H:%M:%S - %d/%m/%y')
    print(f"⬇️ {timestamp} - Mensagem recebida de: {user_id}")

    # Registra uso no CSV
    registro_uso(user_id, user_name, channel_name, current_time, prompt_type)

    # Prepara histórico da conversa
    bot_user_id = app.client.auth_test()["user_id"]
    conversation_history = construct_conversation_history(messages, bot_user_id, user_id, text, thread_ts, ts)
    
    # Posta mensagem de "aguarde"
    status_message_ts = post_message_to_slack(channel_id, please_wait_message, thread_ts)
    
    
    # Execução em thread separada para não travar o bot
    def worker():
        try:
            # Gera resposta da IA
            response, _ = gpt(conversation_history, system_prompt, model="o3-mini" , max_tokens=4095) ### <-- ALTERAR MODELO
            
            # Limpa formatação da resposta
            response = re.sub(r'```[a-zA-Z]+', '```', response)
            response = remover_asteriscos_duplos(response)
            
            # Posta resposta no Slack
            post_message_to_slack(channel_id, response, thread_ts)
            
            # Log customizado da mensagem enviada
            timestamp = datetime.now().strftime('%H:%M:%S - %d/%m/%y')
            print(f"⬆️ {timestamp} - Mensagem enviada para: {user_id}")
        except Exception as e:
            print(f"Erro ao gerar resposta: {e}")
        finally:
            # Remove mensagem de "aguarde"
            if status_message_ts:
                delete_message_from_slack(channel_id, status_message_ts)
    
    # Inicia a thread
    threading.Thread(target=worker).start()


    # Registra uso no CSV
def registro_uso(user_id, user_name, channel_name, current_time, prompt_type):
    fieldnames = ['user_id', 'user_name', 'channel_name', 'timestamp', 'prompt_type']
    try:
        with open('registro_uso.csv', 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if csvfile.tell() == 0:
                writer.writeheader()
            writer.writerow({
                'user_id': user_id,
                'user_name': user_name,
                'channel_name': channel_name,
                'timestamp': current_time,
                'prompt_type': prompt_type
            })
    except Exception as e:
        print(f"Erro ao escrever no arquivo CSV: {e}")

    # Chama a API da OpenAI para gerar resposta
def gpt(conversation_history, system_prompt, model="o3-mini", max_tokens=4095):
    system_message = {
        "role": "system",
        "content": system_prompt
    }
    messages_with_system = [system_message] + conversation_history
    
    request_payload = {
        "model": model,
        "messages": messages_with_system,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": "medium"
    }
    
    response = client.chat.completions.create(**request_payload)
    answer = response.choices[0].message.content if response.choices[0].message.content else "No response content."
    return answer, None

    # Busca histórico de mensagens de uma thread
def fetch_conversation_history(channel_id, thread_ts):
    try:
        history = app.client.conversations_replies(channel=channel_id, ts=thread_ts)
        return history['messages']
    except SlackApiError as e:
        print(f"Falha ao buscar histórico da conversa: {e}")
        if not handle_slack_api_error(e):
            raise
        return []

def handle_slack_api_error(e):
    # Trata erros específicos da API do Slack
    if e.response["error"] in ["missing_scope", "not_in_channel"]:
        print(f"Erro de permissão da API do Slack: {e.response['needed']}")
        return True 
    return False 

def determine_channel_and_user_names(channel_id, user_id):
    # Obtém nomes do usuário e canal a partir dos IDs
    try:
        user_info = app.client.users_info(user=user_id)
        user_name = user_info['user']['real_name']
    except Exception as e:
        print(f"Erro ao buscar nome do usuário: {e}")
        user_name = "Usuário Desconhecido"
    
    try:
        channel_info = app.client.conversations_info(channel=channel_id)
        is_direct_message = channel_info['channel'].get('is_im', False)
        channel_name = "Mensagem Direta" if is_direct_message else channel_info['channel']['name']
    except Exception as e:
        print(f"Erro ao buscar nome do canal: {e}")
        channel_name = "Canal Desconhecido"

    return user_name, channel_name

def construct_conversation_history(messages, bot_user_id, user_id, current_text, thread_ts=None, ts=None):
    # Constrói histórico da conversa no formato esperado pela OpenAI
    conversation_history = []
    for msg in messages:
        role = "user" if msg.get("user") == user_id else "assistant"
        content = msg.get("text")
        if content:
            conversation_history.append({"role": role, "content": content})
    
    # Adiciona mensagem atual se não for uma thread ou for a primeira mensagem
    if not thread_ts or thread_ts == ts:
        conversation_history.append({"role": "user", "content": current_text})
    
    return conversation_history

def post_message_to_slack(channel_id, text, thread_ts=None):
    # Posta mensagem no Slack e retorna timestamp
    if not text: 
        return None
    try:
        response = app.client.chat_postMessage(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts
        )
        return response['ts'] 
    except Exception as e:
        print(f"Falha ao postar mensagem no Slack: {e}")
        return None

def delete_message_from_slack(channel_id, ts):
    # Remove mensagem do Slack
    try:
        app.client.chat_delete(channel=channel_id, ts=ts)
    except Exception as e:
        print(f"Falha ao deletar mensagem do Slack: {e}")

# Handler para eliminar warning de app_home_opened
@app.event("app_home_opened")
def handle_app_home_opened_events(body, logger):
    pass

@app.event("message")
def handle_message_events(body, logger):
    # Handler principal para eventos de mensagem do Slack
    event = body["event"]
    
    # Ignora mensagens que não são de usuários ou têm subtipo
    if 'subtype' in event or 'user' not in event:
        logger.info("Evento ignorado: não é mensagem de usuário ou tem subtipo")
        return

    channel_id = event["channel"]
    text = event["text"]
    user_id = event["user"]
    ts = event.get("ts")
    thread_ts = event.get("thread_ts")
    bot_user_id = app.client.auth_test()["user_id"]
    
    # Responde sempre em mensagens diretas
    if event["channel_type"] == "im":
        ask_chatgpt(text, user_id, channel_id, thread_ts or ts, ts)
        return
        
    # Responde se o bot foi mencionado na mensagem
    if f"<@{bot_user_id}>" in text:
        ask_chatgpt(text, user_id, channel_id, thread_ts or ts, ts)
        return
        
    # Se for resposta em thread, verifica se bot foi mencionado na primeira mensagem
    if thread_ts and thread_ts != ts:
        try:
            thread_history = app.client.conversations_replies(
                channel=channel_id,
                ts=thread_ts
            )
            original_message = next((msg for msg in thread_history['messages'] if msg.get("ts") == thread_ts), None)
            if original_message and f"<@{bot_user_id}>" in original_message.get("text", ""):
                ask_chatgpt(text, user_id, channel_id, thread_ts, ts)
        except Exception as e:
            logger.error(f"Erro ao verificar histórico da thread: {e}")

if __name__ == "__main__":
    print("🤖 Livia está iniciando...")
    print("✅ Conectada ao Slack!")
    try:
        SocketModeHandler(app, SLACK_APP_TOKEN).start()
    except Exception as e:
        print("❌ Livia não esta funcionando.")