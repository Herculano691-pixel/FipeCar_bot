import json
import time
import unicodedata
import logging

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from api import (
    obter_marcas,
    obter_modelos,
    obter_anos,
    obter_preco
)


# ==========================================
# CONFIGURAÇÕES
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

TOKEN = None

URL_BASE = None

usuarios = {}

# Quantidade máxima de opções mostradas por pesquisa
LIMITE_RESULTADOS = 10


# ==========================================
# LEITURA DO TOKEN
# ==========================================

def ler_token():
    try:
        with open(".env", "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                linha = linha.strip()

                if linha.startswith("TELEGRAM_BOT_TOKEN="):
                    return linha.split("=", 1)[1].strip().strip('"')

    except FileNotFoundError:
        logging.error("Arquivo .env não encontrado.")

    return None


# ==========================================
# COMUNICAÇÃO COM O TELEGRAM
# ==========================================

def chamar_telegram(metodo, dados=None):

    url = URL_BASE + metodo

    corpo = json.dumps(dados or {}).encode("utf-8")

    requisicao = Request(
        url,
        data=corpo,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urlopen(requisicao, timeout=35) as resposta:
            resultado = json.loads(
                resposta.read().decode("utf-8")
            )

        if not resultado.get("ok"):
            logging.error("Telegram: %s", resultado.get("description"))

        return resultado

    except HTTPError as erro:
        logging.error("Erro HTTP do Telegram: %s", erro.code)

    except URLError as erro:
        logging.error("Erro de conexão: %s", erro.reason)

    except TimeoutError:
        logging.error("Tempo limite excedido.")

    except json.JSONDecodeError:
        logging.error("Resposta inválida do Telegram.")

    return None


def enviar_mensagem(chat_id, texto):

    dados = {
        "chat_id": chat_id,
        "text": texto
    }

    return chamar_telegram("sendMessage", dados)


# ==========================================
# NORMALIZAÇÃO DE TEXTO
# ==========================================

def normalizar_texto(texto):

    texto = texto.lower().strip()

    texto = unicodedata.normalize("NFD", texto)

    texto = "".join(
        caractere
        for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )

    return texto


# ==========================================
# PESQUISA DE OPÇÕES
# ==========================================

def pesquisar_opcoes(lista, pesquisa):

    pesquisa = normalizar_texto(pesquisa)

    resultados = []

    for item in lista:

        nome = normalizar_texto(item.get("nome", ""))

        if pesquisa in nome:
            resultados.append(item)

    return resultados


def mostrar_opcoes(chat_id, resultados, tipo):

    if not resultados:
        enviar_mensagem(
            chat_id,
            "Não encontrei resultados para essa pesquisa.\n"
            "Tente digitar outro nome."
        )
        return

    resultados = resultados[:LIMITE_RESULTADOS]

    usuarios[chat_id]["opcoes"] = resultados

    mensagem = f"Encontrei estas opções de {tipo}:\n\n"

    for numero, item in enumerate(resultados, start=1):
        mensagem += f"{numero}. {item['nome']}\n"

    mensagem += (
        "\nDigite o número da opção desejada.\n"
        "Ou envie outra pesquisa para filtrar os resultados."
    )

    enviar_mensagem(chat_id, mensagem)


# ==========================================
# SELEÇÃO DE MARCA
# ==========================================

def selecionar_marca(chat_id, texto):

    marcas = obter_marcas()

    resultados = pesquisar_opcoes(marcas, texto)

    mostrar_opcoes(chat_id, resultados, "marcas")


def confirmar_marca(chat_id, numero):

    opcoes = usuarios[chat_id].get("opcoes", [])

    if numero < 1 or numero > len(opcoes):
        enviar_mensagem(chat_id, "Número inválido. Tente novamente.")
        return

    marca = opcoes[numero - 1]

    usuarios[chat_id]["codigo_marca"] = marca["codigo"]
    usuarios[chat_id]["nome_marca"] = marca["nome"]
    usuarios[chat_id]["etapa"] = "modelo"

    enviar_mensagem(
        chat_id,
        f"Marca selecionada: {marca['nome']}\n\n"
        "Agora digite o modelo do veículo."
    )


# ==========================================
# SELEÇÃO DE MODELO
# ==========================================

def selecionar_modelo(chat_id, texto):

    codigo_marca = usuarios[chat_id]["codigo_marca"]

    modelos = obter_modelos(codigo_marca)

    resultados = pesquisar_opcoes(modelos, texto)

    mostrar_opcoes(chat_id, resultados, "modelos")


def confirmar_modelo(chat_id, numero):

    opcoes = usuarios[chat_id].get("opcoes", [])

    if numero < 1 or numero > len(opcoes):
        enviar_mensagem(chat_id, "Número inválido. Tente novamente.")
        return

    modelo = opcoes[numero - 1]

    usuarios[chat_id]["codigo_modelo"] = modelo["codigo"]
    usuarios[chat_id]["nome_modelo"] = modelo["nome"]
    usuarios[chat_id]["etapa"] = "ano"

    chat_id_marca = usuarios[chat_id]["codigo_marca"]

    anos = obter_anos(chat_id_marca, modelo["codigo"])

    if not anos:
        enviar_mensagem(
            chat_id,
            "Não encontrei anos disponíveis para esse modelo."
        )
        return

    usuarios[chat_id]["opcoes"] = anos

    mensagem = "Escolha o ano/versão desejado:\n\n"

    for numero, ano in enumerate(anos, start=1):
        mensagem += f"{numero}. {ano['nome']}\n"

    mensagem += "\nDigite o número da opção."

    enviar_mensagem(chat_id, mensagem)


# ==========================================
# SELEÇÃO DE ANO E CONSULTA
# ==========================================

def confirmar_ano(chat_id, numero):

    opcoes = usuarios[chat_id].get("opcoes", [])

    if numero < 1 or numero > len(opcoes):
        enviar_mensagem(chat_id, "Número inválido. Tente novamente.")
        return

    ano = opcoes[numero - 1]

    codigo_marca = usuarios[chat_id]["codigo_marca"]
    codigo_modelo = usuarios[chat_id]["codigo_modelo"]

    enviar_mensagem(chat_id, "Consultando a Tabela FIPE...")

    resultado = obter_preco(
        codigo_marca,
        codigo_modelo,
        ano["codigo"]
    )

    if not resultado:
        enviar_mensagem(
            chat_id,
            "Não foi possível consultar o preço desse veículo."
        )
        return

    mensagem = (
        "🚗 RESULTADO DA CONSULTA FIPE\n\n"
        f"Marca: {resultado.get('Marca')}\n"
        f"Modelo: {resultado.get('Modelo')}\n"
        f"Ano: {resultado.get('Ano do Modelo')}\n"
        f"Combustível: {resultado.get('Combustível')}\n"
        f"Código FIPE: {resultado.get('Código FIPE')}\n\n"
        f"💰 Valor: {resultado.get('Valor')}\n"
        f"Mês de referência: {resultado.get('Mês de Referência')}\n\n"
        "Para fazer outra consulta, envie /start."
    )

    enviar_mensagem(chat_id, mensagem)

    usuarios.pop(chat_id, None)


# ==========================================
# PROCESSAMENTO DAS MENSAGENS
# ==========================================

def processar_mensagem(chat_id, texto):

    texto = texto.strip()

    if texto == "/start":

        usuarios[chat_id] = {
            "etapa": "marca",
            "opcoes": []
        }

        enviar_mensagem(
            chat_id,
            "🚗 Bem-vindo ao FipeCar_bot!\n\n"
            "Consulte os preços de veículos pela Tabela FIPE.\n\n"
            "Digite o nome da marca que deseja pesquisar.\n\n"
            "Exemplo: Honda, Toyota, Chevrolet."
        )

        return

    if texto == "/cancelar":

        usuarios.pop(chat_id, None)

        enviar_mensagem(
            chat_id,
            "Consulta cancelada!\n"
            "Envie /start para começar novamente."
        )

        return

    if chat_id not in usuarios:

        enviar_mensagem(
            chat_id,
            "Você ainda não iniciou uma consulta.\n"
            "Envie /start para começar."
        )

        return

    etapa = usuarios[chat_id]["etapa"]

    if etapa == "marca":

        if texto.isdigit():
            confirmar_marca(chat_id, int(texto))
        else:
            selecionar_marca(chat_id, texto)

    elif etapa == "modelo":

        if texto.isdigit():
            confirmar_modelo(chat_id, int(texto))
        else:
            selecionar_modelo(chat_id, texto)

    elif etapa == "ano":

        if texto.isdigit():
            confirmar_ano(chat_id, int(texto))
        else:
            enviar_mensagem(
                chat_id,
                "Digite o número do ano desejado."
            )


# ==========================================
# INICIALIZAÇÃO DO BOT
# ==========================================

def iniciar_bot():

    global TOKEN, URL_BASE

    TOKEN = ler_token()

    if not TOKEN:
        logging.error("Configure o TELEGRAM_BOT_TOKEN no arquivo .env.")
        return

    URL_BASE = f"https://api.telegram.org/bot{TOKEN}/"

    logging.info("FipeCar_bot iniciado!")

    ultimo_update = None

    while True:

        dados = {"timeout": 25}

        if ultimo_update is not None:
            dados["offset"] = ultimo_update

        resposta = chamar_telegram("getUpdates", dados)

        if resposta is None:
            time.sleep(3)
            continue

        if not resposta.get("ok"):
            time.sleep(3)
            continue

        atualizacoes = resposta.get("result", [])

        for atualizacao in atualizacoes:

            ultimo_update = atualizacao["update_id"] + 1

            mensagem = atualizacao.get("message")

            if mensagem is None:
                continue

            chat_id = mensagem["chat"]["id"]
            texto = mensagem.get("text", "")

            if texto:
                try:
                    processar_mensagem(chat_id, texto)

                except Exception:
                    logging.exception(
                        "Erro ao processar mensagem do chat %s",
                        chat_id
                    )
                    enviar_mensagem(
                        chat_id,
                        "Ocorreu um erro durante a consulta. "
                        "Tente novamente com /start."
                    )


# ==========================================
# EXECUÇÃO
# ==========================================

if __name__ == "__main__":
    iniciar_bot()