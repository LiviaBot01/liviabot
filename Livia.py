# Livia.py - Chatbot da agência Live para Slack
# Assistente de IA que responde em DMs, canais e threads quando mencionada

import os
import re
import json
import csv
import logging
import threading
import time
from datetime import datetime
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
from openai import OpenAI
from threading import Thread, Lock
import queue

# Configuração de logs
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger('slack_bolt').setLevel(logging.CRITICAL)
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger('openai').setLevel(logging.CRITICAL)

# Carrega e verifica variáveis do .env (se existir) 
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("❌ OPENAI_API_KEY não encontrada. Use: export OPENAI_API_KEY=sua_chave")
if not SLACK_BOT_TOKEN:
    print("❌ SLACK_BOT_TOKEN não encontrada. Use: export SLACK_BOT_TOKEN=seu_token")
if not SLACK_APP_TOKEN:
    print("❌ SLACK_APP_TOKEN não encontrada. Use: export SLACK_APP_TOKEN=seu_token")

# Controle de concorrência para evitar respostas duplicadas
processing_lock = threading.Lock()
processing_messages = {}  # {message_key: timestamp}
message_cooldown = 2  # segundos entre mensagens do mesmo usuário

# Inicialização dos clientes
app = App(
    token=SLACK_BOT_TOKEN,
    process_before_response=True
)
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
    # Cria chave única para a mensagem usando timestamp específico
    message_key = f"{user_id}_{channel_id}_{ts}_{thread_ts or 'main'}"
    current_time_float = time.time()
    
    # Controle de concorrência thread-safe
    with processing_lock:
        # Verifica se já está processando esta mensagem específica
        if message_key in processing_messages:
            return
            
        # Verifica cooldown apenas para mensagens do mesmo usuário no mesmo canal/thread
        cooldown_key = f"{user_id}_{channel_id}_{thread_ts or 'main'}"
        for key, timestamp in list(processing_messages.items()):
            if key.startswith(cooldown_key) and current_time_float - timestamp < message_cooldown:
                return
                
        # Marca mensagem como em processamento
        processing_messages[message_key] = current_time_float
    
    # Verifica conectividade com Slack fora do lock
    try:
        auth_test = app.client.auth_test()
        bot_user_id = auth_test["user_id"]
    except Exception as e:
        with processing_lock:
            if message_key in processing_messages:
                del processing_messages[message_key]
        return
    
    # Remove menções do texto
    text = re.sub(r'<@\w+>', '', text)
    
    # Busca histórico da conversa se for uma thread (e thread_ts for diferente de ts)
    messages = []
    if thread_ts and thread_ts != ts:
        messages = fetch_conversation_history(channel_id, thread_ts)
    
    # Obtém informações do usuário e canal
    user_name, channel_name = determine_channel_and_user_names(channel_id, user_id)
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Carrega configurações do canal
    system_prompt, please_wait_message = load_channel_settings(channel_name, channel_id)
    prompt_type = "Padrão"

    # Log da mensagem recebida
    timestamp = datetime.now().strftime('%H:%M:%S - %d/%m/%y')
    print(f"⬇️ {timestamp} - Mensagem recebida de: {user_id} - Canal: {channel_id}")

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
            response, _ = gpt(conversation_history, system_prompt, model="o3-mini" , max_completion_tokens=4095) ### <-- ALTERAR MODELO
            
            # Limpa formatação da resposta
            response = re.sub(r'```[a-zA-Z]+', '```', response)
            response = remover_asteriscos_duplos(response)
            
            # Posta resposta no Slack
            post_message_to_slack(channel_id, response, thread_ts)
            
            # Log da mensagem enviada
            timestamp = datetime.now().strftime('%H:%M:%S - %d/%m/%y')
            print(f"⬆️ {timestamp} - Mensagem enviada para: {user_id} - Canal: {channel_id}")
        except Exception as e:
            pass
        finally:
            # Remove mensagem de "aguarde"
            if status_message_ts:
                delete_message_from_slack(channel_id, status_message_ts)
                
            # Remove da lista de processamento
            with processing_lock:
                if message_key in processing_messages:
                    del processing_messages[message_key]
                
                # Limpa mensagens antigas do processamento (> 5 minutos)
                current_time = time.time()
                old_keys = [key for key, timestamp in processing_messages.items() 
                           if current_time - timestamp > 300]
                for old_key in old_keys:
                    del processing_messages[old_key]
    
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
        pass

    # Chama a API da OpenAI para gerar resposta
def gpt(conversation_history, system_prompt, model="o3-mini", max_completion_tokens=4095):
    system_message = {
        "role": "system",
        "content": system_prompt
    }
    messages_with_system = [system_message] + conversation_history
    
    request_payload = {
        "model": model,
        "messages": messages_with_system,
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": "medium",
        "timeout": 30  # Timeout de 30 segundos
    }
    
    try:
        response = client.chat.completions.create(**request_payload)
        
        if response and response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip(), None
            else:
                return "Desculpe, não consegui gerar uma resposta.", None
        else:
            return "Desculpe, houve um problema na comunicação.", None
            
    except Exception as e:
        if "timeout" in str(e).lower():
            return "Desculpe, a resposta demorou muito para ser gerada. Tente novamente.", None
        elif "rate_limit" in str(e).lower():
            return "Muitas solicitações. Aguarde um momento e tente novamente.", None
        elif "quota" in str(e).lower() or "billing" in str(e).lower():
            return "Limite de uso atingido. Entre em contato com o administrador.", None
        else:
            return "Desculpe, houve um erro interno. Tente novamente mais tarde.", None

    # Busca histórico de mensagens de uma thread
def fetch_conversation_history(channel_id, thread_ts):
    try:
        history = app.client.conversations_replies(channel=channel_id, ts=thread_ts)
        return history['messages']
    except SlackApiError as e:
        if not handle_slack_api_error(e):
            raise
        return []

def handle_slack_api_error(e):
    # Trata erros específicos da API do Slack
    if e.response["error"] in ["missing_scope", "not_in_channel", "channel_not_found"]:
        return True 
    return False 

def determine_channel_and_user_names(channel_id, user_id):
    # Obtém nomes do usuário e canal a partir dos IDs
    try:
        user_info = app.client.users_info(user=user_id)
        user_name = user_info['user']['real_name']
    except Exception as e:
        user_name = "Usuário Desconhecido"
    
    try:
        channel_info = app.client.conversations_info(channel=channel_id)
        is_direct_message = channel_info['channel'].get('is_im', False)
        channel_name = "Mensagem Direta" if is_direct_message else channel_info['channel']['name']
    except Exception as e:
        channel_name = "Canal Desconhecido"

    return user_name, channel_name

def construct_conversation_history(messages, bot_user_id, user_id, current_text, thread_ts=None, ts=None):
    # Constrói histórico da conversa no formato esperado pela OpenAI
    conversation_history = []
    current_message_found = False
    
    for msg in messages:
        # Verifica se esta é a mensagem atual
        if msg.get("ts") == ts:
            current_message_found = True
            
        role = "user" if msg.get("user") == user_id else "assistant"
        content = msg.get("text")
        if content:
            conversation_history.append({"role": role, "content": content})
    
    # Adiciona mensagem atual apenas se não estiver no histórico
    if not current_message_found:
        conversation_history.append({"role": "user", "content": current_text})
    
    return conversation_history

def post_message_to_slack(channel_id, text, thread_ts=None, max_retries=3):
    """Posta mensagem no Slack com retry automático"""
    if not text: 
        return None
        
    for attempt in range(max_retries):
        try:
            response = app.client.chat_postMessage(
                channel=channel_id,
                text=text,
                thread_ts=thread_ts
            )
            
            if response and response.get("ok"):
                return response.get("ts")
                
        except Exception as e:
            # Log específico para diferentes tipos de erro
            if "rate_limited" in str(e).lower():
                time.sleep(2 ** attempt)  # Backoff exponencial
            elif "channel_not_found" in str(e).lower():
                return None  # Não retry para este tipo de erro
            elif "not_in_channel" in str(e).lower():
                return None  # Não retry para este tipo de erro
        
        # Aguarda antes da próxima tentativa (exceto na última)
        if attempt < max_retries - 1:
            time.sleep(1 + attempt)  # Delay progressivo
    
    return None

def delete_message_from_slack(channel_id, ts):
    # Remove mensagem do Slack
    try:
        app.client.chat_delete(channel=channel_id, ts=ts)
    except Exception as e:
        pass

# Fila para processamento assíncrono de eventos
event_queue = queue.Queue()
processing_lock = Lock()

# Função de monitoramento de saúde do sistema
def health_monitor():
    while True:
        try:
            current_time = time.time()
            
            # Limpa mensagens em processamento antigas (> 2 minutos)
            with processing_lock:
                old_processing = [key for key, timestamp in processing_messages.items() 
                                if current_time - timestamp > 120]
                for key in old_processing:
                    del processing_messages[key]
                if old_processing:
                    print(f"🧹 Limpeza: {len(old_processing)} mensagens antigas removidas do processamento")
            
            # Verifica conectividade com Slack a cada 5 minutos
            try:
                app.client.auth_test()
            except Exception as e:
                print(f"❌ ERRO de conectividade com Slack: {e}")
            
        except Exception as e:
            print(f"❌ ERRO CRÍTICO no monitor de saúde: {e}")
        
        time.sleep(300)

def process_events_worker():
# Worker thread para processar eventos da fila
    while True:
        try:
            event_data = event_queue.get(timeout=1)
            if event_data is None:  # Sinal para parar
                break
            process_message_event(event_data)
            event_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            pass

# Inicialização dos threads
worker_thread = Thread(target=process_events_worker, daemon=True)
health_thread = Thread(target=health_monitor, daemon=True)

worker_thread.start()
health_thread.start()

# Handler para eliminar warning de app_home_opened
@app.event("app_home_opened")
def handle_app_home_opened_events(body, logger):
    pass

@app.event("message")
def handle_message_events(body, logger, ack):
    # Resposta imediata para evitar retries do Slack
    ack()
    
    # Adiciona evento à fila para processamento assíncrono
    event_queue.put(body)

def process_message_event(body):
    """Processa evento de mensagem de forma assíncrona"""
    try:
        event = body["event"]
        
        # Verificação de timestamp para evitar eventos antigos (> 30 segundos)
        current_time = time.time()
        event_time = float(event.get('ts', 0))
        if current_time - event_time > 30:
            return
        
        # Trata mensagens editadas (message_changed) - processamento especial
        if event.get('subtype') == 'message_changed':
            handle_message_changed(event)
            return
        
        # Ignora outras mensagens que não são de usuários
        if 'subtype' in event or 'user' not in event:
            return

        channel_id = event["channel"]
        text = event["text"]
        user_id = event["user"]
        ts = event.get("ts")
        thread_ts = event.get("thread_ts")
        
        # Obtém bot_user_id de forma thread-safe
        try:
            bot_user_id = app.client.auth_test()["user_id"]
        except Exception as e:
            return
        
        # Ignora mensagens do próprio bot
        if user_id == bot_user_id:
            return
        
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
                    ts=thread_ts,
                    limit=1
                )
                original_message = next((msg for msg in thread_history['messages'] if msg.get("ts") == thread_ts), None)
                if original_message and f"<@{bot_user_id}>" in original_message.get("text", ""):
                    ask_chatgpt(text, user_id, channel_id, thread_ts, ts)
            except Exception as e:
                pass
            
    except Exception as e:
        pass

def handle_message_changed(event):
    """Trata eventos de mensagem editada de forma específica"""
    try:
        # Para mensagens editadas, os dados estão dentro de event['message']
        message_data = event.get('message', {})
        previous_message = event.get('previous_message', {})
        
        # Ignora se não há usuário
        if 'user' not in message_data:
            return
        
        current_text = message_data.get('text', '')
        previous_text = previous_message.get('text', '')

        is_new_message = (
            not previous_message or 
            not previous_text or
            (not previous_message.get('thread_ts') and message_data.get('thread_ts')) or
            (previous_message.get('reply_count', -1) != message_data.get('reply_count', -1) and current_text == previous_text) or
            ('subscribed' not in previous_message and 'subscribed' in message_data and current_text == previous_text)
        )
        
        if is_new_message:
            # Processa como mensagem nova
            channel_id = event["channel"]
            text = current_text
            user_id = message_data["user"]
            ts = message_data.get("ts")
            thread_ts = message_data.get("thread_ts")
            
            try:
                bot_user_id = app.client.auth_test()["user_id"]
            except Exception as e:
                return
            
            # Ignora mensagens do próprio bot
            if user_id == bot_user_id:
                return
            
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
                    pass
            return
        
        # Verifica se o texto realmente mudou (ignora atualizações de metadados)
        if current_text == previous_text:
            return
        
        channel_id = event["channel"]
        text = current_text
        user_id = message_data["user"]
        ts = message_data.get("ts")
        thread_ts = message_data.get("thread_ts")
        bot_user_id = app.client.auth_test()["user_id"]
        
        # Responde sempre em mensagens diretas editadas
        if event["channel_type"] == "im":
            ask_chatgpt(text, user_id, channel_id, thread_ts or ts, ts)
            return
            
        # Responde se o bot foi mencionado na mensagem editada
        if f"<@{bot_user_id}>" in text:
            ask_chatgpt(text, user_id, channel_id, thread_ts or ts, ts)
            return
            
    except Exception as e:
        pass

if __name__ == "__main__":
    # Mostra quais chaves estão sendo carregadas
    print(f"🔑 OPENAI_API_KEY: {OPENAI_API_KEY[:10]}...{OPENAI_API_KEY[-4:] if OPENAI_API_KEY else 'NÃO CONFIGURADO'}")
    print(f"🔑 SLACK_BOT_TOKEN: {SLACK_BOT_TOKEN[:10]}...{SLACK_BOT_TOKEN[-4:] if SLACK_BOT_TOKEN else 'NÃO CONFIGURADO'}")
    print(f"🔑 SLACK_APP_TOKEN: {SLACK_APP_TOKEN[:10]}...{SLACK_APP_TOKEN[-4:] if SLACK_APP_TOKEN else 'NÃO CONFIGURADO'}")
    print()
    
    # Verifica se as credenciais estão configuradas
    if not SLACK_BOT_TOKEN:
        print("❌ SLACK_BOT_TOKEN não configurado")
        exit(1)
    if not SLACK_APP_TOKEN:
        print("❌ SLACK_APP_TOKEN não configurado")
        exit(1)
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY não configurado")
        exit(1)
    
    print("🔗 Conectando ao Slack...")
    
    try:
        # Testa conexão com Slack
        auth_test = app.client.auth_test()
        print("✅ Conectado ao Slack!")
        SocketModeHandler(app, SLACK_APP_TOKEN).start()
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        print("❌ Livia não está funcionando.")
