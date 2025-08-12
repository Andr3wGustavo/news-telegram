# main.py
import asyncio
import discord
from discord.ext import commands, tasks
import feedparser
import time
import aiohttp # A nova ferramenta de respiração assíncrona
import sqlite3
import os
import edge_tts
from bs4 import BeautifulSoup
import google.generativeai as genai
from config import DISCORD_TOKEN, DISCORD_CHANNEL_ID, GEMINI_API_KEY, RSS_FEEDS
from datetime import datetime, timezone, timedelta

# --- CONFIGURAÇÃO ---
DB_FILE = "noticias.db"
INTERVALO_VERIFICACAO = 3600
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
BRASILIA_TZ = timezone(timedelta(hours=-3))
EMBED_MAX_LEN = 4000 # Limite seguro para a descrição de um embed

# --- CONFIGURAÇÃO DAS APIS ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- CONFIGURAÇÃO DO BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- ESTADO GLOBAL DO BOT ---
bot_state = {
    "ai_enabled": True,
    "synthesis_mode": "batch" # 'individual' ou 'batch'
}

# --- EXCEÇÃO CUSTOMIZADA ---
class RateLimitException(Exception):
    pass

# --- FUNÇÕES DE MEMÓRIA (BANCO DE DADOS) ---
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

async def processar_noticias_encontradas(channel, noticias):
    if not noticias:
        print("Nenhuma notícia nova para processar.")
        return

    print(f"Encontradas {len(noticias)} notícias novas. Processando no modo '{bot_state['synthesis_mode']}'...")
    try:
        batch_content = ""
        for noticia in noticias:
            texto_artigo = await extrair_texto_artigo(noticia['link'])
            batch_content += f"--- Título: {noticia['title']} (Fonte: {noticia['source']})\nConteúdo: {texto_artigo[:1000] if texto_artigo else 'N/A'}\n\n"
        
        prompt = f"""
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
        resumo = resumir_com_ia(prompt)
        
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

        await gerar_e_enviar_audio(channel, resumo, "Relatório de Inteligência")
        
        for noticia in noticias:
            salvar_noticia(noticia['link'], noticia['source'], noticia['title'])

    except RateLimitException:
        await channel.send("🤖 **Oráculo Informa:**\n\nO limite diário de análises da IA foi atingido.")

# --- TAREFAS EM SEGUNDO PLANO (LOOPS) ---
@tasks.loop(hours=1)
async def ciclo_de_verificacao_horaria():
    print("\n--- Iniciando ciclo de verificação horária ---")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel: return
    noticias = buscar_noticias_novas()
    if noticias:
        await processar_noticias_encontradas(channel, noticias)

@tasks.loop(hours=1)
async def checar_resumo_diario():
    agora_brasilia = datetime.now(BRASILIA_TZ)
    data_hoje = agora_brasilia.date()
    
    if agora_brasilia.hour == 22 and not resumo_diario_ja_enviado(data_hoje):
        print("\n" + "="*50 + "\n!!! HORA DO BRIEFING DIÁRIO !!!\n" + "="*50)
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
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

# --- PAINEL DE CONTROLE INTERATIVO ---
class PainelDeControle(discord.ui.View):
    def __init__(self):
        # MUDANÇA: timeout=None torna a view persistente
        super().__init__(timeout=None)

    # MUDANÇA: Adicionado custom_id para cada botão
    @discord.ui.button(label="Modo Analista", style=discord.ButtonStyle.green, custom_id="persist_analista")
    async def modo_analista(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_state['ai_enabled'] = True
        bot_state['synthesis_mode'] = 'batch'
        await interaction.response.send_message("✅ **Confirmado.** Oráculo agora opera em **Modo Analista**.", ephemeral=True)

    @discord.ui.button(label="Modo Jornalista", style=discord.ButtonStyle.primary, custom_id="persist_jornalista")
    async def modo_jornalista(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_state['ai_enabled'] = True
        bot_state['synthesis_mode'] = 'individual'
        await interaction.response.send_message("✅ **Confirmado.** Oráculo agora opera em **Modo Jornalista**.", ephemeral=True)

    @discord.ui.button(label="Modo Mensageiro", style=discord.ButtonStyle.grey, custom_id="persist_mensageiro")
    async def modo_mensageiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_state['ai_enabled'] = False
        await interaction.response.send_message("✅ **Confirmado.** Análise de IA desativada.", ephemeral=True)

# --- EVENTOS E COMANDOS DO DISCORD ---
@bot.event
async def on_ready():
    print(f'O Oráculo despertou e está online como {bot.user}')
    print('Aguardando o comando !iniciar para começar a vigília.')
    bot.add_view(PainelDeControle())
    checar_resumo_diario.start()

# --- MODAL PARA INÍCIO SUAVE ---
class SoftStartModal(discord.ui.Modal, title='Início Suave'):
    minutes = discord.ui.TextInput(label='Quantos minutos no passado verificar?', placeholder='Ex: 30')

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutos = int(self.minutes.value)
            if minutos <= 0:
                await interaction.response.send_message("Por favor, insira um número positivo.", ephemeral=True)
                return
            
            await interaction.response.send_message(f"✅ **Ordem recebida!** Iniciando vigília com uma busca nos últimos {minutos} minutos...", ephemeral=True)
            
            time_gate = datetime.now(timezone.utc) - timedelta(minutes=minutos)
            noticias = buscar_noticias_novas(time_gate)
            if noticias:
                await processar_noticias_encontradas(interaction.channel, noticias)
            
            if not ciclo_de_verificacao_horaria.is_running():
                ciclo_de_verificacao_horaria.start()

        except ValueError:
            await interaction.response.send_message("Entrada inválida. Por favor, insira um número.", ephemeral=True)

# --- VIEW PARA O COMANDO INICIAR ---
class IniciarView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180) # Botões desaparecem após 3 minutos

    @discord.ui.button(label="Padrão", style=discord.ButtonStyle.green)
    async def padrao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ **Ordem recebida!** Iniciando vigília no modo padrão...", ephemeral=True)
        noticias = buscar_noticias_novas()
        if noticias:
            await processar_noticias_encontradas(interaction.channel, noticias)
        if not ciclo_de_verificacao_horaria.is_running():
            ciclo_de_verificacao_horaria.start()

    @discord.ui.button(label="Início Suave", style=discord.ButtonStyle.primary)
    async def inicio_suave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SoftStartModal())

    @discord.ui.button(label="Sincronizar", style=discord.ButtonStyle.secondary)
    async def sincronizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ **Ordem recebida!** Sincronizando a memória. Isso pode levar um momento...", ephemeral=True)
        noticias = buscar_noticias_novas()
        if noticias:
            for n in noticias:
                salvar_noticia(n['link'], n['source'], n['title'])
            await interaction.followup.send(f"Sincronização completa. {len(noticias)} notícias arquivadas. Iniciando vigília...", ephemeral=True)
        else:
            await interaction.followup.send("Memória já está em dia. Iniciando vigília...", ephemeral=True)
        
        if not ciclo_de_verificacao_horaria.is_running():
            ciclo_de_verificacao_horaria.start()

@bot.command(name='iniciar')
async def iniciar_vigilia(ctx):
    """Inicia a vigília do Oráculo com opções de busca."""
    if ciclo_de_verificacao_horaria.is_running():
        await ctx.send("A vigília horária já está ativa.")
        return
    
    embed = discord.Embed(title="Ordem de Despertar", description="Mestre, como devo iniciar minha vigília?", color=0x7289DA)
    await ctx.send(embed=embed, view=IniciarView())

# --- PONTO DE ENTRADA ---
if __name__ == "__main__":
    setup_database()
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"### ERRO FATAL AO INICIAR O BOT: {e} ###")
        print("-> Verifique se o seu DISCORD_TOKEN está correto no arquivo config.py")