# main.py
import asyncio
import telegram
import feedparser
import time
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, RSS_FEEDS

ARQUIVO_MEMORIA = "links_enviados.txt"
INTERVALO_VERIFICACAO = 3600  # Segundos. 3600 = 1 hora

def ler_links_enviados():
    """Lê o arquivo de memória e retorna um conjunto (set) de links já enviados."""
    try:
        with open(ARQUIVO_MEMORIA, 'r') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def salvar_link_enviado(link):
    """Salva um novo link no arquivo de memória."""
    with open(ARQUIVO_MEMORIA, 'a') as f:
        f.write(link + '\n')

def buscar_noticias_novas(links_ja_enviados):
    """
    Busca em TODOS os feeds RSS e retorna uma lista de notícias novas.
    Formato da lista: [(nome_da_fonte, titulo, link), ...]
    """
    noticias_novas = []
    for nome_fonte, url_feed in RSS_FEEDS.items():
        print(f"Verificando feed: {nome_fonte}...")
        feed = feedparser.parse(url_feed)
        
        if not feed.entries:
            print(f"-> Nenhuma notícia encontrada em {nome_fonte}.")
            continue

        # Iteramos em ordem reversa (do mais antigo para o mais novo no feed)
        # para que o bot envie as notícias na ordem em que foram publicadas.
        for noticia in reversed(feed.entries):
            if noticia.link not in links_ja_enviados:
                print(f"-> Notícia NOVA em {nome_fonte}: {noticia.title}")
                noticias_novas.append((nome_fonte, noticia.title, noticia.link))
                # Adicionamos imediatamente à memória para não pegar a mesma notícia
                # de outro feed se houver duplicatas.
                links_ja_enviados.add(noticia.link)
    
    return noticias_novas

async def enviar_noticia(bot, nome_fonte, titulo, link):
    """
    Envia uma única notícia formatada para o Telegram.
    """
    mensagem = (
        f"📡 **Fonte:** {nome_fonte}\n\n"
        f"🔥 *{titulo}*\n\n"
        f"{link}"
    )
    
    print(f"Enviando para o Telegram: {titulo}")
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, 
            text=mensagem,
            parse_mode='Markdown'
        )
        # O link só é salvo permanentemente no arquivo se o envio for bem sucedido.
        salvar_link_enviado(link)
        # Pequena pausa para não sobrecarregar a API do Telegram
        await asyncio.sleep(1) 
    except Exception as e:
        print(f"### ERRO ao enviar notícia: {e} ###")

async def ciclo_de_verificacao(bot):
    """
    Executa um ciclo completo de verificação e envio de notícias.
    """
    print("\n--- Iniciando novo ciclo de verificação ---")
    links_enviados = ler_links_enviados()
    noticias_para_enviar = buscar_noticias_novas(links_enviados)
    
    if not noticias_para_enviar:
        print("Nenhuma notícia nova em nenhum dos feeds.")
    else:
        print(f"Encontradas {len(noticias_para_enviar)} notícias novas. Enviando...")
        for nome_fonte, titulo, link in noticias_para_enviar:
            await enviar_noticia(bot, nome_fonte, titulo, link)
            
    print("--- Ciclo finalizado. Aguardando próximo intervalo. ---")

async def main():
    """
    Função principal que mantém o bot rodando em um loop infinito.
    """
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    print(">>> Bot de Notícias iniciado. Pressione Ctrl+C para parar. <<<")
    
    while True:
        await ciclo_de_verificacao(bot)
        print(f"Aguardando {INTERVALO_VERIFICACAO / 60} minutos para o próximo ciclo...")
        await asyncio.sleep(INTERVALO_VERIFICACAO)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Bot encerrado pelo usuário. <<<")