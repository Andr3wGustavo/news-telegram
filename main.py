import asyncio
import telegram
import feedparser
import time
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, RSS_FEEDS
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÃO ---
ARQUIVO_MEMORIA = "links_enviados.txt"
INTERVALO_VERIFICACAO = 3600  # 1 hora
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Configura a API do Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- EXCEÇÃO CUSTOMIZADA ---
class RateLimitException(Exception):
    pass

# --- FUNÇÕES DE MEMÓRIA ---
def ler_links_enviados():
    try:
        with open(ARQUIVO_MEMORIA, 'r') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def salvar_link_enviado(link):
    with open(ARQUIVO_MEMORIA, 'a') as f:
        f.write(link + '\n')

# --- FUNÇÕES DE PROCESSAMENTO DE NOTÍCIA ---
def extrair_texto_artigo(url):
    # (Esta função não muda)
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
            element.decompose()
        text = ' '.join(p.get_text(strip=True) for p in soup.find_all('p'))
        return text if len(text) > 200 else None
    except Exception as e:
        print(f"### ERRO ao extrair texto de {url}: {e} ###")
        return None

def resumir_com_ia(texto_artigo, titulo):
    # (Esta função não muda)
    if not texto_artigo:
        return "Não foi possível extrair o conteúdo para resumir."
    prompt = f"""
    Analise a seguinte notícia com o título "{titulo}".
    Destile a informação em seus pontos mais essenciais e críticos.
    Me forneça um resumo conciso e direto em 3 a 5 bullet points (usando •).
    Seja direto e foque no impacto e na informação chave.
    Notícia:
    {texto_artigo[:8000]}
    """
    try:
        print("-> Enviando para análise do Gemini...")
        response = model.generate_content(prompt)
        print("-> Resumo recebido.")
        return response.text
    except Exception as e:
        if "429" in str(e) and "quota" in str(e).lower():
            raise RateLimitException("Quota da API do Gemini excedida.")
        print(f"### ERRO na API do Gemini: {e} ###")
        return "A IA não conseguiu processar esta notícia."

# --- FUNÇÕES DO BOT ---
def buscar_noticias_novas(links_ja_enviados, time_gate=None):
    noticias_novas = []
    for nome_fonte, url_feed in RSS_FEEDS.items():
        print(f"Verificando feed: {nome_fonte}...")
        feed = feedparser.parse(url_feed)
        if not feed.entries: continue
        for noticia in reversed(feed.entries):
            if noticia.link in links_ja_enviados:
                continue
            if time_gate and 'published_parsed' in noticia:
                try:
                    noticia_dt = datetime.fromtimestamp(time.mktime(noticia.published_parsed), tz=timezone.utc)
                    if noticia_dt < time_gate:
                        continue
                except Exception:
                    pass
            print(f"-> Notícia NOVA em {nome_fonte}: {noticia.title}")
            noticias_novas.append((nome_fonte, noticia.title, noticia.link))
            links_ja_enviados.add(noticia.link)
    return noticias_novas

async def enviar_resumo(bot, nome_fonte, titulo, link, resumo, dry_run=False):
    mensagem = (
        f"📡 **Fonte:** {nome_fonte}\n\n"
        f"🔥 **{titulo}**\n\n"
        f"🧠 **Síntese do Oráculo:**\n{resumo}\n\n"
        f"🔗 *Link Original:* {link}"
    )
    if dry_run:
        print(f"DRY RUN: Notícia '{titulo}' não será enviada.")
        return
    print(f"Enviando resumo para o Telegram: {titulo}")
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem, parse_mode='Markdown')
        salvar_link_enviado(link)
        await asyncio.sleep(2)
    except Exception as e:
        print(f"### ERRO ao enviar resumo: {e} ###")

async def ciclo_de_verificacao(bot, config):
    print("\n--- Iniciando novo ciclo de verificação ---")
    links_enviados = ler_links_enviados()
    
    # Modo 3: Sincronizar Agora
    if config['mode'] == 'sync':
        print("!!! MODO SINCRONIZAÇÃO ATIVADO !!!")
        noticias_para_sincronizar = buscar_noticias_novas(links_enviados)
        if not noticias_para_sincronizar:
            print("Nenhuma notícia encontrada para sincronizar. Memória já está atualizada.")
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🤖 **Oráculo Informa:**\n\nMemória já está em dia. Nenhuma notícia nova para sincronizar.")
            return
        
        for _, _, link in noticias_para_sincronizar:
            salvar_link_enviado(link)
        
        print(f"{len(noticias_para_sincronizar)} notícias foram adicionadas à memória sem envio.")
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"🤖 **Oráculo Informa:**\n\nSincronização completa. {len(noticias_para_sincronizar)} notícias do passado foram arquivadas. A partir de agora, apenas o futuro será notificado.")
        return

    # Modos 1 e 2: Início Padrão ou com Tempo
    time_gate = None
    if config['mode'] == 'time':
        time_gate = datetime.now(timezone.utc) - timedelta(minutes=config['minutes'])
        print(f"!!! INÍCIO SUAVE ATIVADO. Processando apenas notícias desde: {time_gate.strftime('%Y-%m-%d %H:%M:%S UTC')} !!!")

    noticias_para_processar = buscar_noticias_novas(links_enviados, time_gate=time_gate)
    
    if not noticias_para_processar:
        print("Nenhuma notícia nova em nenhum dos feeds.")
        return

    print(f"Encontradas {len(noticias_para_processar)} notícias novas. Processando...")
    try:
        for nome_fonte, titulo, link in noticias_para_processar:
            texto_artigo = extrair_texto_artigo(link)
            resumo = resumir_com_ia(texto_artigo, titulo)
            await enviar_resumo(bot, nome_fonte, titulo, link, resumo, dry_run=config['dry_run'])
    except RateLimitException:
        print("Ciclo interrompido devido a rate limit. Notificando o usuário.")
        if not config['dry_run']:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🤖 **Oráculo Informa:**\n\nO limite diário de análises da IA foi atingido.")

def mostrar_menu_e_obter_config():
    """Apresenta o menu interativo e retorna um dicionário com as configurações escolhidas."""
    config = {'mode': 'standard', 'minutes': 0, 'dry_run': False, 'continuous': False}
    
    print("="*40)
    print("--- Painel de Controle do Oráculo ---")
    print("="*40)
    print("[1] Início Padrão (Usa a memória para evitar duplicatas)")
    print("[2] Início Suave (Busca notícias de um passado recente)")
    print("[3] Sincronizar Agora (Ignora o passado, prepara para o futuro)")
    print("\n[9] Sair")
    
    while True:
        escolha = input("\nSua escolha de modo: ")
        if escolha == '1':
            config['mode'] = 'standard'
            break
        elif escolha == '2':
            config['mode'] = 'time'
            while True:
                try:
                    minutos = int(input("Quantos minutos no passado deseja verificar? "))
                    config['minutes'] = minutos
                    break
                except ValueError:
                    print("Por favor, insira um número válido.")
            break
        elif escolha == '3':
            config['mode'] = 'sync'
            break
        elif escolha == '9':
            return None # Sinal para sair
        else:
            print("Opção inválida. Tente novamente.")

    print("\n--- Opções Adicionais ---")
    opcoes = input("Pressione Enter para rodar um ciclo, ou digite 'C' para Contínuo e/ou 'D' para Simulação (Dry Run) (ex: CD): ").upper()
    if 'C' in opcoes:
        config['continuous'] = True
    if 'D' in opcoes:
        config['dry_run'] = True
        print("\n!!! MODO SIMULAÇÃO (DRY RUN) ATIVADO. NADA SERÁ ENVIADO OU SALVO. !!!")

    return config

async def main():
    config = mostrar_menu_e_obter_config()
    if config is None:
        print("Encerrando a pedido do Mestre.")
        return

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    
    if not config['continuous']:
        print(">>> Oráculo de Notícias com IA iniciado (modo de ciclo único). <<<")
        await ciclo_de_verificacao(bot, config)
        print("\n--- Ciclo único finalizado. ---")
    else:
        print(">>> Oráculo de Notícias com IA iniciado (modo contínuo). Pressione Ctrl+C para parar. <<<")
        while True:
            await ciclo_de_verificacao(bot, config)
            print(f"\nAguardando {INTERVALO_VERIFICACAO / 60} minutos para o próximo ciclo...")
            await asyncio.sleep(INTERVALO_VERIFICACAO)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Bot encerrado pelo usuário. <<<")
    except Exception as e:
        print(f"\n!!! Ocorreu um erro fatal: {e} !!!")
