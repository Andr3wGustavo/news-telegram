import asyncio
import telegram
import feedparser
import time
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, RSS_FEEDS, GEMINI_API_KEY

# --- CONFIGURAÇÃO ---
ARQUIVO_MEMORIA = "links_enviados.txt"
INTERVALO_VERIFICACAO = 3600  # 1 hora
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Configura a API do Gemini
genai.configure(api_key=GEMINI_API_KEY)
generation_config = {
  "temperature": 0.5,
  "top_p": 1,
  "top_k": 1,
  "max_output_tokens": 2048,
}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]
# --- CORREÇÃO APLICADA AQUI ---
# O modelo 'gemini-1.0-pro-latest' estava obsoleto. Usamos um modelo mais recente.
model = genai.GenerativeModel('gemini-1.5-flash-latest',
                              generation_config=generation_config,
                              safety_settings=safety_settings)

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
    """Visita a URL e tenta extrair o texto principal do artigo."""
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove elementos desnecessários
        for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
            element.decompose()
            
        # Pega todo o texto restante e limpa
        text = ' '.join(p.get_text(strip=True) for p in soup.find_all('p'))
        return text if len(text) > 200 else None # Retorna None se o texto for muito curto
    except Exception as e:
        print(f"### ERRO ao extrair texto de {url}: {e} ###")
        return None

def resumir_com_ia(texto_artigo, titulo):
    """Envia o texto para o Gemini e pede um resumo."""
    if not texto_artigo:
        return "Não foi possível extrair o conteúdo para resumir."
    
    prompt = f"""
    Analise a seguinte notícia com o título "{titulo}".
    Destile a informação em seus pontos mais essenciais e críticos.
    Me forneça um resumo conciso e direto em 3 a 5 bullet points (usando •).
    Seja direto e foque no impacto e na informação chave. todas as respostas devem ser em portugues
    

    Notícia:
    {texto_artigo[:8000]}
    """
    try:
        print("-> Enviando para análise do Gemini...")
        response = model.generate_content(prompt)
        print("-> Resumo recebido.")
        return response.text
    except Exception as e:
        print(f"### ERRO na API do Gemini: {e} ###")
        return "A IA não conseguiu processar esta notícia."

# --- FUNÇÕES DO BOT ---
def buscar_noticias_novas(links_ja_enviados):
    # (Esta função permanece idêntica à da Fase 5)
    noticias_novas = []
    for nome_fonte, url_feed in RSS_FEEDS.items():
        print(f"Verificando feed: {nome_fonte}...")
        feed = feedparser.parse(url_feed)
        if not feed.entries: continue
        for noticia in reversed(feed.entries):
            if noticia.link not in links_ja_enviados:
                print(f"-> Notícia NOVA em {nome_fonte}: {noticia.title}")
                noticias_novas.append((nome_fonte, noticia.title, noticia.link))
                links_ja_enviados.add(noticia.link)
    return noticias_novas

async def enviar_resumo(bot, nome_fonte, titulo, link, resumo):
    """Envia o resumo da notícia formatado para o Telegram."""
    mensagem = (
        f"📡 **Fonte:** {nome_fonte}\n\n"
        f"🔥 **{titulo}**\n\n"
        f"🧠 **Síntese do Oráculo:**\n{resumo}\n\n"
        f"🔗 *Link Original:* {link}"
    )
    
    print(f"Enviando resumo para o Telegram: {titulo}")
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, 
            text=mensagem,
            parse_mode='Markdown'
        )
        salvar_link_enviado(link)
        await asyncio.sleep(2) # Pausa maior pois envolve IA
    except Exception as e:
        print(f"### ERRO ao enviar resumo: {e} ###")

async def ciclo_de_verificacao(bot):
    """Executa um ciclo completo de verificação, resumo e envio."""
    print("\n--- Iniciando novo ciclo de verificação ---")
    links_enviados = ler_links_enviados()
    noticias_para_processar = buscar_noticias_novas(links_enviados)
    
    if not noticias_para_processar:
        print("Nenhuma notícia nova em nenhum dos feeds.")
    else:
        print(f"Encontradas {len(noticias_para_processar)} notícias novas. Processando...")
        for nome_fonte, titulo, link in noticias_para_processar:
            texto_artigo = extrair_texto_artigo(link)
            resumo = resumir_com_ia(texto_artigo, titulo)
            await enviar_resumo(bot, nome_fonte, titulo, link, resumo)
            
    print("--- Ciclo finalizado. Aguardando próximo intervalo. ---")

async def main():
    """Função principal que mantém o bot rodando em um loop infinito."""
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    print(">>> Oráculo de Notícias com IA iniciado. Pressione Ctrl+C para parar. <<<")
    
    while True:
        await ciclo_de_verificacao(bot)
        print(f"Aguardando {INTERVALO_VERIFICACAO / 60} minutos para o próximo ciclo...")
        await asyncio.sleep(INTERVALO_VERIFICACAO)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Bot encerrado pelo usuário. <<<")