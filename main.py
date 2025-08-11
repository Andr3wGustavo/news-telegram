# main.py
import asyncio
import telegram
import feedparser
import time
import requests
import sqlite3
import argparse
import os
import edge_tts # A voz primária (nobre, mas temperamental)
from gtts import gTTS # A voz secundária (confiável, o plano B)
from bs4 import BeautifulSoup
import google.generativeai as genai
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, RSS_FEEDS
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÃO ---
DB_FILE = "noticias.db"
TELEGRAM_MAX_LEN = 4096
INTERVALO_VERIFICACAO = 3600
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
BRASILIA_TZ = timezone(timedelta(hours=-3))

# --- CONFIGURAÇÃO DAS APIS ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- EXCEÇÃO CUSTOMIZADA ---
class RateLimitException(Exception):
    pass

# --- FUNÇÕES DE MEMÓRIA (BANCO DE DADOS) ---
def setup_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS noticias (
            link TEXT PRIMARY KEY, source TEXT, title TEXT, first_seen TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_summary_log (summary_date DATE PRIMARY KEY)
    ''')
    conn.commit()
    conn.close()

def link_foi_visto(link):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM noticias WHERE link = ?", (link,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def salvar_noticia(link, source, title):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO noticias (link, source, title, first_seen) VALUES (?, ?, ?, ?)",
                   (link, source, title, datetime.now(timezone.utc)))
    conn.commit()
    conn.close()

def buscar_noticias_diarias():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    cursor.execute("SELECT source, title FROM noticias WHERE first_seen >= ?", (twenty_four_hours_ago,))
    results = [{'source': row[0], 'title': row[1]} for row in cursor.fetchall()]
    conn.close()
    return results

def resumo_diario_ja_enviado(check_date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM daily_summary_log WHERE summary_date = ?", (check_date,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def marcar_resumo_diario_como_enviado(sent_date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO daily_summary_log (summary_date) VALUES (?)", (sent_date,))
    conn.commit()
    conn.close()

# --- FUNÇÕES DE PROCESSAMENTO ---
def extrair_texto_artigo(url):
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
            element.decompose()
        text = ' '.join(p.get_text(strip=True) for p in soup.find_all('p'))
        return text if len(text) > 200 else None
    except Exception as e:
        print(f"### ERRO ao extrair texto de {url}: {e} ###")
        return None

def resumir_com_ia(prompt):
    try:
        print("-> Enviando para análise do Gemini...")
        response = model.generate_content(prompt)
        print("-> Resumo recebido.")
        return response.text
    except Exception as e:
        if "429" in str(e) and "quota" in str(e).lower():
            raise RateLimitException("Quota da API do Gemini excedida.")
        print(f"### ERRO na API do Gemini: {e} ###")
        return "A IA não conseguiu processar esta requisição."

# --- FUNÇÕES DO BOT ---
def buscar_noticias_novas(time_gate=None):
    noticias_novas = []
    for nome_fonte, url_feed in RSS_FEEDS.items():
        print(f"Verificando feed: {nome_fonte}...")
        feed = feedparser.parse(url_feed)
        if not feed.entries: continue
        for noticia in reversed(feed.entries):
            if link_foi_visto(noticia.link):
                continue
            if time_gate and 'published_parsed' in noticia:
                try:
                    noticia_dt = datetime.fromtimestamp(time.mktime(noticia.published_parsed), tz=timezone.utc)
                    if noticia_dt < time_gate:
                        continue
                except Exception:
                    pass
            print(f"-> Notícia NOVA em {nome_fonte}: {noticia.title}")
            noticias_novas.append({'source': nome_fonte, 'title': noticia.title, 'link': noticia.link})
    return noticias_novas

async def enviar_mensagem(bot, mensagem_texto):
    if len(mensagem_texto) <= TELEGRAM_MAX_LEN:
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem_texto, parse_mode='Markdown')
        except Exception:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem_texto)
        finally:
            await asyncio.sleep(1)
            return

    partes = []
    chunk_size = TELEGRAM_MAX_LEN - 50
    for i in range(0, len(mensagem_texto), chunk_size):
        partes.append(mensagem_texto[i:i + chunk_size])
    for i, parte in enumerate(partes):
        parte_com_header = f"**(Parte {i+1}/{len(partes)})**\n\n{parte}"
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=parte_com_header, parse_mode='Markdown')
        except Exception:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=parte_com_header)
        finally:
            await asyncio.sleep(2)

async def gerar_e_enviar_audio(bot, texto, titulo_audio, nome_arquivo='audio_temp.mp3'):
    """Tenta gerar áudio com Edge TTS, e se falhar, usa gTTS como fallback."""
    
    texto_limpo = texto.replace('*', '').replace('_', '').replace('`', '')
    texto_limpo = texto_limpo.replace('•', '. ').replace('🧠','').replace('🔥','')
    texto_limpo = texto_limpo.replace('📡','').replace('📰','').replace('🔗','')
    texto_limpo = texto_limpo.replace('🗓️','')

    try:
        # TENTATIVA 1: A Voz Nobre (Edge TTS)
        # MUDANÇA: Trocando a voz para "Francisca" e removendo a aceleração.
        VOICE = "pt-BR-FranciscaNeural"
        print(f"-> Tentando gerar áudio com Edge TTS (Voz: {VOICE})...")
        communicate = edge_tts.Communicate(texto_limpo, VOICE)
        await communicate.save(nome_arquivo)
    except Exception as e:
        print(f"### FALHA com Edge TTS: {e} ###")
        print("--- TENTANDO COM A VOZ SECUNDÁRIA (gTTS) ---")
        try:
            # TENTATIVA 2: A Voz Confiável (gTTS)
            tts = gTTS(text=texto_limpo, lang='pt-br', slow=False)
            tts.save(nome_arquivo)
        except Exception as e2:
            print(f"### FALHA com gTTS também: {e2} ###")
            await enviar_mensagem(bot, f"🤖 **Oráculo Alerta:**\n\nHouve uma falha crítica ao gerar a narração para '{titulo_audio}'. Ambas as vozes falharam.")
            return

    try:
        print(f"-> Áudio salvo como {nome_arquivo}. Enviando...")
        with open(nome_arquivo, 'rb') as audio_file:
            await bot.send_audio(chat_id=TELEGRAM_CHAT_ID, audio=audio_file, title=titulo_audio, caption="Sua análise narrada pelo Oráculo.")
        print("-> Áudio enviado com sucesso.")
    except Exception as e:
        print(f"### ERRO ao enviar o arquivo de áudio: {e} ###")
    finally:
        if os.path.exists(nome_arquivo):
            os.remove(nome_arquivo)


async def ciclo_de_verificacao(bot, config):
    print("\n--- Iniciando novo ciclo de verificação em tempo real ---")
    
    if config['mode'] == 'sync':
        print("!!! MODO SINCRONIZAÇÃO ATIVADO !!!")
        noticias_para_sincronizar = buscar_noticias_novas()
        if noticias_para_sincronizar:
            for noticia in noticias_para_sincronizar:
                salvar_noticia(noticia['link'], noticia['source'], noticia['title'])
            await enviar_mensagem(bot, f"🤖 **Oráculo Informa:**\n\nSincronização completa. {len(noticias_para_sincronizar)} notícias do passado foram arquivadas.")
        else:
            await enviar_mensagem(bot, "🤖 **Oráculo Informa:**\n\nMemória já está em dia.")
        config['mode'] = 'standard'
        return

    noticias_para_processar = buscar_noticias_novas(config.get('time_gate'))
    
    if not noticias_para_processar:
        print("Nenhuma notícia nova em nenhum dos feeds.")
        return

    print(f"Encontradas {len(noticias_para_processar)} notícias novas. Processando...")
    try:
        if config['ai_enabled'] and config['synthesis_mode'] == 'batch':
            print("--- MODO ANALISTA ATIVADO ---")
            batch_content = ""
            for noticia in noticias_para_processar:
                texto_artigo = extrair_texto_artigo(noticia['link'])
                batch_content += f"--- Título: {noticia['title']} (Fonte: {noticia['source']})\nConteúdo: {texto_artigo[:1000] if texto_artigo else 'N/A'}\n\n"
            
            prompt_lote = f"""
            Você é um analista de inteligência. A seguir está um dossiê de notícias. Sua tarefa é criar um único "Relatório de Inteligência" conciso.

            1.  **Síntese Geral:** Comece com um parágrafo curto que resuma o cenário geral das notícias.
            1.1 **Para cada notícia que julgar importante, seja mais detalhista.**
            1.2 **Preciso que foque nas coisas revolucionárias e pegue os LANÇAMENTOS e novidades em uma parte separada, como nome de cada sigla.**
            1.3 **Selecione as 7 principais notícias, e seja mais específico quando for resumi-las.**
            2.  **Temas Principais:** Identifique de 5 a 15 temas recorrentes. Para cada tema, liste os pontos chave em bullet points (•).
            3.  **Conexões e Implicações:** Aponte conexões entre as notícias ou possíveis implicações de cada uma.
            
            Seja direto, analítico e foque no que é mais importante.
            --- Dossiê de Notícias ---
            {batch_content}
            """
            resumo_geral = resumir_com_ia(prompt_lote)
            mensagem_final = f"🧠 **RELATÓRIO DE INTELIGÊNCIA** 🧠\n\n{resumo_geral}"
            await enviar_mensagem(bot, mensagem_final)
            await gerar_e_enviar_audio(bot, resumo_geral, "Relatório de Inteligência")
            for noticia in noticias_para_processar:
                salvar_noticia(noticia['link'], noticia['source'], noticia['title'])

        else: # Modo Jornalista ou Mensageiro
            print("--- MODO JORNALISTA/MENSAGEIRO ATIVADO ---")
            for noticia in noticias_para_processar:
                salvar_noticia(noticia['link'], noticia['source'], noticia['title'])
                if config['ai_enabled']:
                    texto_artigo = extrair_texto_artigo(noticia['link'])
                    prompt = f"Resuma esta notícia em 3 a 5 bullet points: '{noticia['title']}'. Conteúdo de apoio: {texto_artigo[:2000] if texto_artigo else 'N/A'}"
                    resumo = resumir_com_ia(prompt)
                    mensagem = f"📡 **Fonte:** {noticia['source']}\n🔥 **{noticia['title']}**\n\n{resumo}\n\n🔗 *Link Original:* {noticia['link']}"
                    await enviar_mensagem(bot, mensagem)
                    await gerar_e_enviar_audio(bot, resumo, noticia['title'])
                else:
                    mensagem = f"📡 **Fonte:** {noticia['source']}\n📰 *{noticia['title']}*\n\n🔗 *Link:* {noticia['link']}"
                    await enviar_mensagem(bot, mensagem)

    except RateLimitException:
        await enviar_mensagem(bot, "🤖 **Oráculo Informa:**\n\nO limite diário de análises da IA foi atingido.")

async def checar_e_enviar_resumo_diario(bot):
    agora_brasilia = datetime.now(BRASILIA_TZ)
    data_hoje = agora_brasilia.date()
    
    if agora_brasilia.hour >= 22 and not resumo_diario_ja_enviado(data_hoje):
        print("\n" + "="*50 + "\n!!! HORA DO BRIEFING DIÁRIO !!!\n" + "="*50)
        noticias_do_dia = buscar_noticias_diarias()
        if not noticias_do_dia:
            await enviar_mensagem(bot, "🤖 **Oráculo Informa:**\n\nNenhuma notícia registrada nas últimas 24 horas.")
            marcar_resumo_diario_como_enviado(data_hoje)
            return

        batch_content = "".join([f"- {n['title']} ({n['source']})\n" for n in noticias_do_dia])
        prompt_diario = f"Crie um 'Briefing Diário' baseado nestas manchetes das últimas 24 horas. Comece com um parágrafo geral, depois os 3-5 destaques principais em bullet points, e uma conclusão sobre o que observar amanhã.\n\nManchetes:\n{batch_content}"
        resumo_geral = resumir_com_ia(prompt_diario)
        mensagem_final = f"🗓️ **BRIEFING DIÁRIO DO ORÁCULO** 🗓️\n\n{resumo_geral}"
        await enviar_mensagem(bot, mensagem_final)
        await gerar_e_enviar_audio(bot, resumo_geral, "Briefing Diário do Oráculo")
        marcar_resumo_diario_como_enviado(data_hoje)
        print("--- BRIEFING DIÁRIO ENVIADO ---")

def mostrar_menu_e_obter_config():
    config = {'mode': 'standard', 'continuous': False, 'ai_enabled': True, 'synthesis_mode': 'individual', 'time_gate': None}
    
    print("\n" + "="*50 + "\n" + " " * 10 + "--- PAINEL DE CONTROLE DO ORÁCULO ---\n" + "="*50)
    print("\n[MODO DE OPERAÇÃO]: Qual é a minha missão?")
    print("-" * 50)
    print("  [1] Vigília Padrão (Análise em tempo real)")
    print("  [2] Início Suave (Vigília a partir de um passado recente)")
    print("  [3] Sincronizar Agora (Arquiva o passado, prepara para o futuro)")
    print("\n  [9] Sair")

    while True:
        escolha_missao = input("\nSua escolha de missão: ")
        if escolha_missao == '1':
            config['mode'] = 'standard'
            break
        elif escolha_missao == '2':
            config['mode'] = 'time'
            while True:
                try:
                    minutos = int(input("  Quantos minutos no passado deseja verificar? "))
                    config['time_gate'] = datetime.now(timezone.utc) - timedelta(minutes=minutos)
                    break
                except ValueError:
                    print("  Por favor, insira um número válido.")
            break
        elif escolha_missao == '3':
            config['mode'] = 'sync'
            break
        elif escolha_missao == '9':
            return None
        else:
            print("  Opção inválida.")

    if config['mode'] in ['standard', 'time']:
        print("\n  [MODO DE ANÁLISE]: Como devo pensar?")
        print("  ---------------------------------------")
        print("    [A] Modo Jornalista (Notícia por notícia)")
        print("    [B] Modo Analista (Relatório único)")
        print("    [C] Modo Mensageiro (Apenas links)")
        while True:
            escolha_analise = input("\n    Sua escolha de análise: ").upper()
            if escolha_analise == 'A':
                config['synthesis_mode'] = 'individual'
                break
            elif escolha_analise == 'B':
                config['synthesis_mode'] = 'batch'
                break
            elif escolha_analise == 'C':
                config['ai_enabled'] = False
                break
            else:
                print("    Opção inválida.")

    print("\n" + "-"*50 + "\n[MODO DE EXECUÇÃO]: Como devo operar?\n" + "-" * 50)
    opcoes = input("  Pressione [Enter] para um ciclo, ou 'C' para Contínuo: ").upper()
    if 'C' in opcoes:
        config['continuous'] = True

    return config

async def main(args):
    setup_database()
    
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    
    config = {}
    if args.auto_run:
        print("--- MODO DE AUTOMAÇÃO ATIVADO ---")
        config = {'mode': 'standard', 'continuous': True, 'ai_enabled': not args.no_ai, 
                  'synthesis_mode': 'batch' if args.batch else 'individual', 'time_gate': None}
    else:
        config = mostrar_menu_e_obter_config()
        if config is None:
            print("\nEncerrando a pedido do Mestre.")
            return
    
    if not config.get('continuous', False):
        print("\n>>> Oráculo em modo de ciclo único. <<<")
        if config['mode'] != 'sync':
            await checar_e_enviar_resumo_diario(bot)
        await ciclo_de_verificacao(bot, config)
        print("\n--- Ciclo único finalizado. ---")
    else:
        print("\n>>> Oráculo em modo contínuo. Pressione Ctrl+C para parar. <<<")
        while True:
            await checar_e_enviar_resumo_diario(bot)
            await ciclo_de_verificacao(bot, config)
            print(f"\nAguardando {INTERVALO_VERIFICACAO / 60} minutos para o próximo ciclo...")
            await asyncio.sleep(INTERVALO_VERIFICACAO)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot de Notícias com IA para Telegram.")
    parser.add_argument('--auto-run', action='store_true', help="Inicia o bot em modo contínuo sem menu.")
    parser.add_argument('--batch', action='store_true', help="No modo auto-run, usa a análise em lote.")
    parser.add_argument('--no-ai', action='store_true', help="No modo auto-run, desativa a IA.")
    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\n>>> Bot encerrado pelo usuário. <<<")
    except Exception as e:
        print(f"\n!!! Ocorreu um erro fatal: {e} !!!")