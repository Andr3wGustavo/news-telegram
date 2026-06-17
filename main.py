# main.py
import asyncio
import discord
from discord.ext import commands, tasks
import feedparser
import time
import aiohttp
import sqlite3
import os
import edge_tts
from bs4 import BeautifulSoup
import google.generativeai as genai
from config import DISCORD_TOKEN, GEMINI_API_KEY, CHANNELS, RSS_FEEDS_CATEGORIZADOS
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÃO ---
DB_FILE = "noticias.db"
INTERVALO_VERIFICACAO = 7200
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
BRASILIA_TZ = timezone(timedelta(hours=-3))
EMBED_MAX_LEN = 4000

# --- CONFIGURAÇÃO DAS APIS ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- CONFIGURAÇÃO DO BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- ESTADO GLOBAL DO BOT ---
bot_state = {
    "ai_enabled": True,
    "synthesis_mode": "batch"
}

# --- EXCEÇÃO CUSTOMIZADA ---
class RateLimitException(Exception):
    pass

# --- FUNÇÕES DE MEMÓRIA E ARQUIVO ---
def salvar_em_markdown(categoria, noticias, resumo):
    if not os.path.exists('registros_md'):
        os.makedirs('registros_md')
    data_hora = datetime.now(BRASILIA_TZ).strftime("%Y-%m-%d_%H-%M")
    nome_arquivo = f"registros_md/{categoria.replace(' ', '_').replace('/', '_')}_{data_hora}.md"
    
    conteudo = f"# Resumo: {categoria} - {data_hora}\n\n"
    conteudo += f"## Análise da IA\n\n{resumo}\n\n"
    conteudo += "---\n## Notícias Coletadas\n\n"
    for n in noticias:
        conteudo += f"- **{n['title']}** ({n['source']})\n  Link: {n['link']}\n"
    
    try:
        with open(nome_arquivo, 'w', encoding='utf-8') as f:
            f.write(conteudo)
    except Exception as e:
        print(f"Erro ao salvar markdown: {e}")

def setup_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS noticias (link TEXT PRIMARY KEY, source TEXT, title TEXT, first_seen TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS daily_summary_log (summary_date DATE PRIMARY KEY)')
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
async def extrair_texto_artigo(url):
    headers = {'User-Agent': USER_AGENT}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as response:
                response.raise_for_status()
                html_content = await response.text()
                loop = asyncio.get_running_loop()
                soup = await loop.run_in_executor(None, BeautifulSoup, html_content, 'html.parser')
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
def buscar_noticias_novas(feeds, time_gate=None):
    noticias_novas = []
    for nome_fonte, url_feed in feeds.items():
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

async def gerar_e_enviar_audio(channel, texto, titulo_audio, nome_arquivo='audio_temp.mp3'):
    VOICE = "pt-BR-FranciscaNeural"
    try:
        print(f"-> Gerando áudio com Edge TTS (Voz: {VOICE})...")
        texto_limpo = texto.replace('*', '').replace('_', '').replace('`', '').replace('•', '. ')
        communicate = edge_tts.Communicate(texto_limpo, VOICE)
        await communicate.save(nome_arquivo)
        print(f"-> Áudio salvo como {nome_arquivo}. Enviando...")
        with open(nome_arquivo, 'rb') as audio_file:
            await channel.send(file=discord.File(audio_file))
        print("-> Áudio enviado com sucesso.")
    except Exception as e:
        print(f"### ERRO ao gerar ou enviar áudio: {e} ###")
        await channel.send(f"🤖 **Oráculo Alerta:** Houve uma falha ao tentar gerar a narração.")
    finally:
        if os.path.exists(nome_arquivo):
            os.remove(nome_arquivo)

async def processar_noticias_encontradas(channel, noticias, categoria):
    if not noticias:
        print("Nenhuma notícia nova para processar.")
        return

    print(f"Encontradas {len(noticias)} notícias novas. Processando no Modo Analista...")
    try:
        batch_content = ""
        for noticia in noticias:
            texto_artigo = await extrair_texto_artigo(noticia['link'])
            batch_content += f"--- Título: {noticia['title']} (Fonte: {noticia['source']})\nConteúdo: {texto_artigo[:1000] if texto_artigo else 'N/A'}\n\n"
        
        prompt = f"""
        Você é um analista de inteligência. A seguir está um dossiê de notícias da categoria "{categoria}". Sua tarefa é criar um único "Relatório de Inteligência" conciso.

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
        resumo = resumir_com_ia(prompt)
        
        # Salva o resumo localmente
        salvar_em_markdown(categoria, noticias, resumo)
        
        if len(resumo) <= EMBED_MAX_LEN:
            embed = discord.Embed(title="🧠 Relatório de Inteligência do Oráculo", description=f"```\n{resumo}\n```", color=0x00ff00)
            embed.set_footer(text=f"Análise de {len(noticias)} notícias.")
            await channel.send(embed=embed)
        else:
            partes = [resumo[i:i + EMBED_MAX_LEN] for i in range(0, len(resumo), EMBED_MAX_LEN)]
            for i, parte in enumerate(partes):
                titulo_parte = f"🧠 Relatório de Inteligência (Volume {i+1}/{len(partes)})"
                embed = discord.Embed(title=titulo_parte, description=f"```\n{parte}\n```", color=0x00ff00)
                if i == len(partes) - 1:
                    embed.set_footer(text=f"Análise de {len(noticias)} notícias.")
                await channel.send(embed=embed)
                await asyncio.sleep(1)

        await gerar_e_enviar_audio(channel, resumo, f"Relatório de Inteligência - {categoria}")
        
        for noticia in noticias:
            salvar_noticia(noticia['link'], noticia['source'], noticia['title'])

    except RateLimitException:
        await channel.send("🤖 **Oráculo Informa:**\n\nO limite diário de análises da IA foi atingido.")

# --- TAREFAS EM SEGUNDO PLANO (LOOPS) ---
@tasks.loop(hours=2)
async def ciclo_de_verificacao():
    # MUDANÇA: Adicionada a lógica de vigília e repouso.
    agora_brasilia = datetime.now(BRASILIA_TZ)
    if not (6 <= agora_brasilia.hour < 22):
        print(f"({agora_brasilia.strftime('%H:%M')}) Oráculo em modo de repouso. Próxima vigília às 06:00.")
        return

    print(f"\n({agora_brasilia.strftime('%H:%M')}) --- Iniciando ciclo de verificação (a cada 2h) ---")
    
    for categoria, feeds in RSS_FEEDS_CATEGORIZADOS.items():
        print(f"--- Processando Categoria: {categoria} ---")
        channel_id = CHANNELS.get(categoria, 0)
        if not channel_id:
            print(f"Aviso: Canal para a categoria '{categoria}' não configurado. Pulando...")
            continue
        
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"Aviso: Não foi possível acessar o canal ID {channel_id} para '{categoria}'.")
            continue
            
        noticias = buscar_noticias_novas(feeds)
        if noticias:
            await processar_noticias_encontradas(channel, noticias, categoria)
        else:
            print(f"Sem notícias novas para {categoria}.")
        await asyncio.sleep(2) # Pequena pausa entre categorias

@tasks.loop(hours=1)
async def checar_resumo_diario():
    agora_brasilia = datetime.now(BRASILIA_TZ)
    data_hoje = agora_brasilia.date()
    
    if agora_brasilia.hour == 22 and not resumo_diario_ja_enviado(data_hoje):
        print("\n" + "="*50 + "\n!!! HORA DO BRIEFING DIÁRIO !!!\n" + "="*50)
        # Envia no canal da primeira categoria disponível ou em todos? 
        # Vamos enviar no principal (Cripto e Economia) para evitar spam em todos.
        channel_id = CHANNELS.get("Cripto e Economia", 0)
        channel = bot.get_channel(channel_id)
        if not channel: return
        
        noticias_do_dia = buscar_noticias_diarias()
        if not noticias_do_dia:
            await channel.send("🤖 **Oráculo Informa:** Nenhuma notícia registrada nas últimas 24 horas.")
        else:
            batch_content = "".join([f"- {n['title']} ({n['source']})\n" for n in noticias_do_dia])
            prompt = f"Crie um 'Briefing Diário' baseado nestas manchetes das últimas 24 horas..."
            resumo = resumir_com_ia(prompt)
            embed = discord.Embed(title="🗓️ Briefing Diário do Oráculo", description=f"```\n{resumo}\n```", color=0xFFD700)
            await channel.send(embed=embed)
            await gerar_e_enviar_audio(channel, resumo, "Briefing Diário do Oráculo")
        
        marcar_resumo_diario_como_enviado(data_hoje)
        print("--- BRIEFING DIÁRIO ENVIADO ---")

# --- EVENTOS E COMANDOS DO DISCORD ---
class ScanButton(discord.ui.Button):
    def __init__(self, categoria):
        super().__init__(label=f"Escanear {categoria}", style=discord.ButtonStyle.success, custom_id=f"scan_{categoria}")
        self.categoria = categoria

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🤖 Iniciando scan manual para **{self.categoria}**...", ephemeral=True)
        feeds = RSS_FEEDS_CATEGORIZADOS.get(self.categoria, {})
        channel_id = CHANNELS.get(self.categoria, 0)
        if channel_id == 0:
            await interaction.followup.send(f"❌ Canal para {self.categoria} não configurado.", ephemeral=True)
            return
            
        channel = bot.get_channel(channel_id)
        if not channel:
            await interaction.followup.send(f"❌ Canal para {self.categoria} não encontrado.", ephemeral=True)
            return

        noticias = buscar_noticias_novas(feeds)
        if not noticias:
            await interaction.followup.send(f"✅ Scan concluído. Nenhuma notícia nova para {self.categoria}.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Encontradas {len(noticias)} notícias novas para {self.categoria}. Processando e enviando para o canal correspondente...", ephemeral=True)
            await processar_noticias_encontradas(channel, noticias, self.categoria)

class PainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for categoria in RSS_FEEDS_CATEGORIZADOS.keys():
            self.add_item(ScanButton(categoria))

@bot.event
async def on_ready():
    print(f'O Oráculo despertou e está online como {bot.user}')
    bot.add_view(PainelView()) # Persistir botões após reinício
    try:
        synced = await bot.tree.sync()
        print(f"Sincronizados {len(synced)} comandos em barra (Slash Commands).")
    except Exception as e:
        print(f"Erro ao sincronizar comandos em barra: {e}")
    ciclo_de_verificacao.start()
    checar_resumo_diario.start()

@bot.tree.command(name='painel', description='Envia o painel interativo para escanear categorias manualmente.')
async def painel(interaction: discord.Interaction):
    embed = discord.Embed(title="🎛️ Painel de Controle do Oráculo", description="Clique em um botão para forçar uma verificação manual de uma categoria específica.", color=0x00A2E8)
    if interaction.client.user and interaction.client.user.display_avatar:
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, view=PainelView())

@bot.tree.command(name='verificar', description='Avisa sobre o comando /painel.')
async def manual_check(interaction: discord.Interaction):
    await interaction.response.send_message("🤖 **Atenção:** O comando `/verificar` foi substituído pelo comando `/painel`. Use `/painel` para abrir o dashboard e escolher qual categoria deseja escanear.", ephemeral=True)

# --- PONTO DE ENTRADA ---
if __name__ == "__main__":
    setup_database()
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"### ERRO FATAL AO INICIAR O BOT: {e} ###")
        print("-> Verifique se o seu DISCORD_TOKEN está correto no arquivo config.py")