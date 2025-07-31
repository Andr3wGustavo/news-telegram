# main.py
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
<<<<<<< HEAD
=======

>>>>>>> c094e47993142bebd992c53d03987cd173e4b4ee
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

<<<<<<< HEAD
def resumir_com_ia(prompt):
    """Função genérica para enviar um prompt para a IA."""
=======
def resumir_com_ia(texto_artigo, titulo):
    
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
>>>>>>> c094e47993142bebd992c53d03987cd173e4b4ee
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
            noticias_novas.append({'source': nome_fonte, 'title': noticia.title, 'link': noticia.link})
    return noticias_novas

async def enviar_mensagem(bot, mensagem_texto):
    """Função genérica para enviar qualquer mensagem para o Telegram."""
    try:
        # Tenta enviar com Markdown
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem_texto, parse_mode='Markdown')
    except Exception as e:
        print(f"### ERRO ao enviar com Markdown: {e} ###")
        print("--- Tentando enviar como texto simples ---")
        try:
            # Se falhar, envia como texto simples para garantir a entrega
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem_texto)
        except Exception as e2:
            print(f"### ERRO ao enviar como texto simples: {e2} ###")
    finally:
        await asyncio.sleep(1)


async def ciclo_de_verificacao(bot, config):
    print("\n--- Iniciando novo ciclo de verificação ---")
    links_enviados = ler_links_enviados()
    
    if config['mode'] == 'sync':
        print("!!! MODO SINCRONIZAÇÃO ATIVADO !!!")
        noticias_para_sincronizar = buscar_noticias_novas(links_enviados)
        if not noticias_para_sincronizar:
            print("Nenhuma notícia encontrada para sincronizar. Memória já está atualizada.")
            await enviar_mensagem(bot, "🤖 **Oráculo Informa:**\n\nMemória já está em dia. Nenhuma notícia nova para sincronizar.")
        else:
            for noticia in noticias_para_sincronizar:
                salvar_link_enviado(noticia['link'])
            print(f"{len(noticias_para_sincronizar)} notícias foram adicionadas à memória sem envio.")
            await enviar_mensagem(bot, f"🤖 **Oráculo Informa:**\n\nSincronização completa. {len(noticias_para_sincronizar)} notícias do passado foram arquivadas.")
        config['mode'] = 'standard'
        print("--- MODO DE OPERAÇÃO ALTERADO PARA 'PADRÃO' PARA OS PRÓXIMOS CICLOS ---")
        return

    time_gate = config.get('time_gate')
    noticias_para_processar = buscar_noticias_novas(links_enviados, time_gate)
    
    if not noticias_para_processar:
        print("Nenhuma notícia nova em nenhum dos feeds.")
        return

    print(f"Encontradas {len(noticias_para_processar)} notícias novas. Processando...")
    
    try:
        if config['ai_enabled'] and config['synthesis_mode'] == 'batch':
            print("--- MODO ANALISTA ATIVADO ---")
            batch_content = ""
            for i, noticia in enumerate(noticias_para_processar):
                print(f"Extraindo texto da notícia {i+1}/{len(noticias_para_processar)}: {noticia['title']}")
                texto_artigo = extrair_texto_artigo(noticia['link'])
                # **FIX 1: Resiliência contra erro 403**
                if texto_artigo:
                    batch_content += f"--- Notícia {i+1} ---\nFonte: {noticia['source']}\nTítulo: {noticia['title']}\nConteúdo: {texto_artigo[:1500]}\n\n"
                else:
                    # Fallback: Usa apenas o título se a extração falhar
                    batch_content += f"--- Notícia {i+1} (Conteúdo bloqueado/indisponível) ---\nFonte: {noticia['source']}\nTítulo: {noticia['title']}\n\n"
            
            if not batch_content:
                print("Não foi possível obter títulos ou conteúdo de nenhuma notícia para o relatório.")
                return

            prompt_lote = f"""
            Você é um analista de inteligência. A seguir está um dossiê de notícias. Algumas podem ter o conteúdo completo, outras apenas o título. Sua tarefa é criar um único "Relatório de Inteligência" conciso baseado na informação disponível.
            1.  **Síntese Geral:** Comece com um parágrafo curto que resuma o cenário geral.
            2.  **Temas Principais:** Identifique de 2 a 4 temas recorrentes. Para cada tema, liste os pontos chave em bullet points (•).
            3.  **Conexões e Implicações:** Aponte conexões entre as notícias ou possíveis implicações.
            Seja direto, analítico e foque no que é mais importante.
            --- Dossiê de Notícias ---
            {batch_content}
            """
            resumo_geral = resumir_com_ia(prompt_lote)
            # **FIX 2: Prevenção de erro de Markdown**
            mensagem_final = f"🧠 **RELATÓRIO DE INTELIGÊNCIA DO ORÁCULO** 🧠\n\n```\n{resumo_geral}\n```"
            await enviar_mensagem(bot, mensagem_final)
            for noticia in noticias_para_processar:
                salvar_link_enviado(noticia['link'])
        else:
            print("--- MODO JORNALISTA/MENSAGEIRO ATIVADO ---")
            for noticia in noticias_para_processar:
                if config['ai_enabled']:
                    texto_artigo = extrair_texto_artigo(noticia['link'])
                    prompt_individual = f"""
                    Analise a seguinte notícia com o título "{noticia['title']}".
                    Destile a informação em seus pontos mais essenciais e críticos em 3 a 5 bullet points (usando •).
                    Baseie-se no conteúdo a seguir, se disponível: {texto_artigo[:8000] if texto_artigo else 'Conteúdo não disponível.'}
                    """
                    resumo = resumir_com_ia(prompt_individual)
                    # **FIX 2: Prevenção de erro de Markdown**
                    mensagem = (f"📡 **Fonte:** {noticia['source']}\n\n🔥 **{noticia['title']}**\n\n"
                                f"🧠 **Síntese do Oráculo:**\n```\n{resumo}\n```\n\n🔗 *Link Original:* {noticia['link']}")
                else: # Modo Mensageiro
                    mensagem = (f"📡 **Fonte:** {noticia['source']}\n\n"
                                f"📰 *{noticia['title']}*\n\n"
                                f"🔗 *Link:* {noticia['link']}")
                await enviar_mensagem(bot, mensagem)
                salvar_link_enviado(noticia['link'])

    except RateLimitException:
        print("!!! LIMITE DE QUOTA ATINGIDO. !!!")
        await enviar_mensagem(bot, "🤖 **Oráculo Informa:**\n\nO limite diário de análises da IA foi atingido. A missão foi abortada para este ciclo.")

def mostrar_menu_e_obter_config():
    """Apresenta o menu interativo e retorna um dicionário com as configurações escolhidas."""
    config = {'mode': 'standard', 'minutes': 0, 'dry_run': False, 'continuous': False, 'ai_enabled': True, 'synthesis_mode': 'individual', 'time_gate': None}
    
    print("\n" + "="*50)
    print(" " * 10 + "--- PAINEL DE CONTROLE DO ORÁCULO ---")
    print("="*50)
    
    print("\n[MODO DE ANÁLISE]: Como devo pensar?")
    print("-" * 50)
    print("  [1] Modo Jornalista (Analisa e envia notícia por notícia)")
    print("  [2] Modo Analista (Agrupa tudo em um único relatório de inteligência)")
    print("  [3] Modo Mensageiro (Envia apenas os links, sem análise de IA)")
    while True:
        escolha_analise = input("\nSua escolha de análise: ")
        if escolha_analise == '1':
            config['synthesis_mode'] = 'individual'
            break
        elif escolha_analise == '2':
            config['synthesis_mode'] = 'batch'
            break
        elif escolha_analise == '3':
            config['ai_enabled'] = False
            config['synthesis_mode'] = 'individual' # Define um padrão
            break
        else:
            print("  Opção inválida.")

    print("\n" + "-"*50)
    print("[MODO DE BUSCA]: Como devo olhar para o passado?")
    print("-" * 50)
    print("  [1] Início Padrão (Usa a memória para evitar duplicatas)")
    print("  [2] Início Suave (Busca notícias de um passado recente)")
    print("  [3] Sincronizar Agora (Arquiva o passado, prepara para o futuro)")
    while True:
        escolha_busca = input("\nSua escolha de busca: ")
        if escolha_busca == '1':
            config['mode'] = 'standard'
            break
        elif escolha_busca == '2':
            config['mode'] = 'time'
            while True:
                try:
                    minutos = int(input("  Quantos minutos no passado deseja verificar? "))
                    config['time_gate'] = datetime.now(timezone.utc) - timedelta(minutes=minutos)
                    break
                except ValueError:
                    print("  Por favor, insira um número válido.")
            break
        elif escolha_busca == '3':
            config['mode'] = 'sync'
            break
<<<<<<< HEAD
=======
        elif escolha == '9':
            return None 
>>>>>>> c094e47993142bebd992c53d03987cd173e4b4ee
        else:
            print("  Opção inválida.")

    print("\n" + "-"*50)
    print("[MODO DE EXECUÇÃO]: Como devo operar após a busca?")
    print("-" * 50)
    opcoes = input("  Pressione [Enter] para rodar um ciclo.\n  Digite 'C' para Contínuo e/ou 'D' para Simulação (ex: CD): ").upper()
    if 'C' in opcoes:
        config['continuous'] = True
    if 'D' in opcoes:
        config['dry_run'] = True
        print("\n!!! MODO SIMULAÇÃO (DRY RUN) ATIVADO. NADA SERÁ ENVIADO OU SALVO. !!!")

    return config

async def main():
    config = mostrar_menu_e_obter_config()
    if config is None:
        print("\nEncerrando a pedido do Mestre.")
        return

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    
    if not config['continuous']:
        print("\n>>> Oráculo de Notícias com IA iniciado (modo de ciclo único). <<<")
        await ciclo_de_verificacao(bot, config)
        print("\n--- Ciclo único finalizado. ---")
    else:
        print("\n>>> Oráculo de Notícias com IA iniciado (modo contínuo). Pressione Ctrl+C para parar. <<<")
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
