# config.py - Configuração para o Bot de Notícias Multi-temático
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- CHAVES SECRETAS ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- CANAIS DO DISCORD ---
CHANNELS = {
    "Cripto e Economia": int(os.getenv("CHANNEL_ID_CRIPTO", 0)) if os.getenv("CHANNEL_ID_CRIPTO") else 0,
    "Mundo": int(os.getenv("CHANNEL_ID_MUNDO", 0)) if os.getenv("CHANNEL_ID_MUNDO") else 0,
    "Tecnologia": int(os.getenv("CHANNEL_ID_TECNOLOGIA", 0)) if os.getenv("CHANNEL_ID_TECNOLOGIA") else 0,
    "Brasil": int(os.getenv("CHANNEL_ID_BRASIL", 0)) if os.getenv("CHANNEL_ID_BRASIL") else 0,
}

# --- FONTES DE SABEDORIA (FEEDS RSS CATEGORIZADOS) ---
RSS_FEEDS_CATEGORIZADOS = {
    "Cripto e Economia": {
        "Cointelegraph": "https://cointelegraph.com/rss",
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "The Block": "https://www.theblock.co/rss.xml",
        "Decrypt": "https://decrypt.co/feed",
        "CryptoSlate": "https://cryptoslate.com/feed/",
        "BeInCrypto": "https://beincrypto.com/feed/",
        "InfoMoney": "https://www.infomoney.com.br/feed/",
        "Valor Economico": "https://valor.globo.com/rss/valor/",
        "Bloomberg Markets": "https://feeds.bloomberg.com/markets/news.rss",
        "Wall Street Journal Markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    },
    "Mundo": {
        "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "G1 Mundo": "https://g1.globo.com/rss/g1/mundo/",
    },
    "Tecnologia": {
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "TechCrunch": "https://techcrunch.com/feed/",
        "Wired": "https://www.wired.com/feed/rss",
        "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
        "Canaltech": "https://canaltech.com.br/rss/",
    },
    "Brasil": {
        "G1 Brasil": "https://g1.globo.com/rss/g1/",
        "CNN Brasil": "https://www.cnnbrasil.com.br/feed/",
        "Folha Poder": "https://feeds.folha.uol.com.br/poder/rss091.xml",
    }
}

