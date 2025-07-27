import asyncio
import telegram
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

async def enviar_mensagem_teste():
    """
    Função principal que inicializa o bot e envia uma mensagem de teste.
    """
    print("Iniciando o bot...")
    bot = telegram.Bot(token=TELEGRAM_TOKEN)

    mensagem = "O templo foi erguido e a alma foi invocada. Estou vivo."

    print(f"Enviando mensagem para o Chat ID: {TELEGRAM_CHAT_ID}")
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, 
            text=mensagem
        )
        print("Mensagem enviada com sucesso!")
    except Exception as e:
        print(f"Ocorreu um erro: {e}")

if __name__ == "__main__":
    
    asyncio.run(enviar_mensagem_teste())


