import json
import time
import socket
import unicodedata
import logging

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from api import (
    obter_marcas,
    obter_modelos,
    obter_anos,
    obter_preco,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

usuarios = {}
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

def _requisicao(metodo, dados, tentativas, timeout):
    url = f"https://api.telegram.org/bot{usuarios.get('_token')}/{metodo}"
    corpo = json.dumps(dados or {}).encode("utf-8")
    requisicao = Request(
        url,
        data=corpo,
        headers={"Content-Type": "application/json"},
    )

    erro_ultimo = None
    for tentativa in range(1, tentativas + 1):
        try:
            with urlopen(requisicao, timeout=timeout) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except HTTPError as erro:
            logging.error("Erro HTTP do Telegram: %s", erro.code)
            return None
        except URLError as erro:
            erro_ultimo = erro
            motivo = getattr(erro, "reason", erro)
            if isinstance(motivo, (ConnectionResetError, socket.error)) or "10054" in str(motivo):
                logging.warning(
                    "Conexão resetada (tentativa %d/%d). Tentando novamente...",
                    tentativa, tentativas,
                )
            else:
                logging.error("Erro de conexão: %s", motivo)
                return None
        except TimeoutError:
            erro_ultimo = "tempo limite excedido"
            logging.warning(
                "Tempo limite excedido (tentativa %d/%d).", tentativa, tentativas,
            )
        except json.JSONDecodeError:
            logging.error("Resposta inválida do Telegram.")
            return None

        if tentativa < tentativas:
            time.sleep(2 ** (tentativa - 1))

    logging.error(
        "Falha ao conectar ao Telegram após %d tentativas. Último erro: %s",
        tentativas, erro_ultimo,
    )
    return None


def _telegram(metodo, dados=None, tentativas=3, timeout=35):
    return _requisicao(metodo, dados, tentativas, timeout)


def enviar(chat_id, texto):
    return _telegram("sendMessage", {"chat_id": chat_id, "text": texto})


def editar(chat_id, message_id, texto, reply_markup=None):
    dados = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": texto,
    }
    if reply_markup is not None:
        dados["reply_markup"] = reply_markup
    # Edição de UI: 1 tentativa e timeout curto para não travar a troca de página
    return _telegram("editMessageText", dados, tentativas=1, timeout=8)


def answer_callback(callback_query_id):
    # Resposta imediata ao callback: remove o "relógio" do botão o mais rápido possível
    _telegram(
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id},
        tentativas=1,
        timeout=5,
    )


# ==========================================
# NORMALIZAÇÃO E PESQUISA
# ==========================================

def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto.lower().strip())
    return "".join(
        c for c in texto if unicodedata.category(c) != "Mn"
    )


def filtrar(lista, pesquisa):
    pesquisa = normalizar(pesquisa)
    return [i for i in lista if pesquisa in normalizar(i.get("nome", ""))]


# ==========================================
# AJUDA DE NAVEGAÇÃO (PAGINAÇÃO)
# ==========================================

def _total_paginas(itens):
    return (len(itens) + LIMITE_RESULTADOS - 1) // LIMITE_RESULTADOS


def _botoes_modelos(opcoes, pagina, total_paginas):
    linhas = []
    inicio = pagina * LIMITE_RESULTADOS
    for i, item in enumerate(opcoes[inicio:inicio + LIMITE_RESULTADOS], start=inicio):
        linhas.append([{"text": item["nome"], "callback_data": f"model:{i}"}])

    nav = []
    if pagina > 0:
        nav.append({"text": "⬅️ Anterior", "callback_data": "page:prev"})
    if pagina < total_paginas - 1:
        nav.append({"text": "Próxima ➡️", "callback_data": "page:next"})
    if nav:
        linhas.append(nav)
    return {"inline_keyboard": linhas}


def exibir_modelos(chat_id, pagina=0, message_id=None, intro=None):
    opcoes = usuarios[chat_id].get("opcoes", [])
    if not opcoes:
        enviar(chat_id, "⚠️ Não encontrei modelos para essa marca.")
        return

    total = _total_paginas(opcoes)
    nome_marca = usuarios[chat_id].get("nome_marca", "")
    texto = ""
    if intro:
        texto += f"{intro}\n"
    texto += (
        f"📋 Modelos de {nome_marca} "
        f"(página {pagina + 1} de {total}):\n\n"
        "Escolha um modelo abaixo.\n"
    )

    if message_id:
        editar(chat_id, message_id, texto, _botoes_modelos(opcoes, pagina, total))
    else:
        resposta = _telegram(
            "sendMessage",
            {"chat_id": chat_id, "text": texto, "reply_markup": _botoes_modelos(opcoes, pagina, total)},
        )
        if resposta and resposta.get("ok"):
            usuarios[chat_id]["message_id_modelos"] = resposta["result"]["message_id"]


def mudar_pagina(chat_id, direcao, message_id):
    pagina = usuarios[chat_id].get("page", 0) + direcao
    opcoes = usuarios[chat_id].get("opcoes", [])
    total = _total_paginas(opcoes)
    if 0 <= pagina < total:
        usuarios[chat_id]["page"] = pagina
        exibir_modelos(chat_id, pagina=pagina, message_id=message_id)


def processar_callback(chat_id, message_id, data):
    if data.startswith("model:"):
        try:
            indice = int(data.split(":", 1)[1])
        except ValueError:
            return
        confirmar_opcao(chat_id, indice + 1, etapa="modelo")
    elif data in ("page:prev", "page:next"):
        message_id = message_id or usuarios[chat_id].get("message_id_modelos")
        mudar_pagina(chat_id, -1 if data == "page:prev" else 1, message_id)


# ==========================================
# SELEÇÃO (MARCA / MODELO / ANO)
# ==========================================

def confirmar_opcao(chat_id, numero, etapa):
    """Confirma a opção selecionada (marca, modelo ou ano)."""
    opcoes = usuarios[chat_id].get("opcoes", [])
    if numero < 1 or numero > len(opcoes):
        enviar(chat_id, "⚠️ Número inválido. Tente novamente.")
        return

    item = opcoes[numero - 1]

    if etapa == "marca":
        usuarios[chat_id].update({
            "codigo_marca": item["codigo"],
            "nome_marca": item["nome"],
            "etapa": "modelo",
        })
        modelos = obter_modelos(item["codigo"])
        usuarios[chat_id]["opcoes"] = modelos
        usuarios[chat_id]["modelos_completos"] = modelos
        usuarios[chat_id]["page"] = 0
        exibir_modelos(
            chat_id,
            pagina=0,
            intro=(
                f"✅ Marca selecionada: {item['nome']}\n"
                "🔍 Toque em um modelo abaixo ou digite para filtrar.\n"
            ),
        )

    elif etapa == "modelo":
        usuarios[chat_id].update({
            "codigo_modelo": item["codigo"],
            "nome_modelo": item["nome"],
            "etapa": "ano",
        })
        anos = obter_anos(usuarios[chat_id]["codigo_marca"], item["codigo"])
        if not anos:
            enviar(chat_id, "⚠️ Não encontrei anos disponíveis para esse modelo.")
            return
        usuarios[chat_id]["opcoes"] = anos
        enviar(chat_id, "📅 Escolha o ano/versão desejado:\n\n" + "\n".join(
            f"{i}. {a['nome']}" for i, a in enumerate(anos, 1)
        ) + "\n\nDigite o número da opção.")

    elif etapa == "ano":
        codigo_marca = usuarios[chat_id]["codigo_marca"]
        codigo_modelo = usuarios[chat_id]["codigo_modelo"]
        enviar(chat_id, "🔍 Consultando a Tabela FIPE...")
        resultado = obter_preco(codigo_marca, codigo_modelo, item["codigo"])
        if not resultado:
            enviar(chat_id, "❌ Não foi possível consultar o preço desse veículo.")
            return
        enviar(chat_id, (
            "🚗 RESULTADO DA CONSULTA FIPE\n\n"
            f"Marca: {resultado.get('Marca')}\n"
            f"Modelo: {resultado.get('Modelo')}\n"
            f"Ano: {resultado.get('Ano do Modelo')}\n"
            f"Combustível: {resultado.get('Combustível')}\n"
            f"💰 Valor: {resultado.get('Valor')}\n\n"
            "Para fazer outra consulta, envie /start."
        ))
        usuarios.pop(chat_id, None)


def selecionar(chat_id, texto, etapa, buscar):
    """Pesquisa e exibe opções (marca ou modelo)."""
    if etapa == "marca":
        lista = obter_marcas()
    else:
        lista = usuarios[chat_id].get("modelos_completos") or buscar(usuarios[chat_id].get("codigo_marca", ""))

    resultados = filtrar(lista, texto)
    usuarios[chat_id]["opcoes"] = resultados
    usuarios[chat_id]["page"] = 0

    if etapa == "modelo":
        exibir_modelos(chat_id, pagina=0)
    else:
        if not resultados:
            enviar(chat_id, "🔍 Não encontrei resultados para essa pesquisa.\nTente digitar outro nome.")
            return
        resultados = resultados[:LIMITE_RESULTADOS]
        usuarios[chat_id]["opcoes"] = resultados
        mensagem = f"🔍 Encontrei estas opções de {etapa}s:\n\n" + "\n".join(
            f"{i}. {item['nome']}" for i, item in enumerate(resultados, 1)
        ) + "\n\nDigite o número da opção desejada.\nOu envie outra pesquisa para filtrar os resultados."
        enviar(chat_id, mensagem)


# ==========================================
# PROCESSAMENTO DAS MENSAGENS
# ==========================================

def processar_mensagem(chat_id, texto):
    texto = texto.strip()

    if texto == "/start":
        usuarios[chat_id] = {"etapa": "marca", "opcoes": []}
        enviar(chat_id, (
            "🚗 Bem-vindo ao FipeCar_bot!\n\n"
            "Consulte os preços de veículos pela Tabela FIPE.\n\n"
            "Digite o nome da marca que deseja pesquisar.\n\n"
            "Exemplo: Honda, Toyota, Chevrolet."
        ))
        return

    if texto == "/cancelar":
        usuarios.pop(chat_id, None)
        enviar(chat_id, "❌ Consulta cancelada!\nEnvie /start para começar novamente.")
        return

    if chat_id not in usuarios:
        enviar(chat_id, "ℹ️ Você ainda não iniciou uma consulta.\nEnvie /start para começar.")
        return

    etapa = usuarios[chat_id]["etapa"]

    if etapa == "marca":
        if texto.isdigit():
            confirmar_opcao(chat_id, int(texto), "marca")
        else:
            selecionar(chat_id, texto, "marca", obter_marcas)

    elif etapa == "modelo":
        if texto.isdigit():
            confirmar_opcao(chat_id, int(texto), "modelo")
        else:
            selecionar(chat_id, texto, "modelo", lambda _: usuarios[chat_id].get("modelos_completos", []))

    elif etapa == "ano":
        if texto.isdigit():
            confirmar_opcao(chat_id, int(texto), "ano")
        else:
            enviar(chat_id, "1️⃣ Digite o número do ano desejado.")


# ==========================================
# INICIALIZAÇÃO DO BOT
# ==========================================

def iniciar_bot():
    token = ler_token()
    if not token:
        logging.error("Configure o TELEGRAM_BOT_TOKEN no arquivo .env.")
        return

    usuarios["_token"] = token
    logging.info("FipeCar_bot iniciado!")

    ultimo_update = None

    while True:
        dados = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
        if ultimo_update is not None:
            dados["offset"] = ultimo_update

        resposta = _telegram("getUpdates", dados)
        if resposta is None:
            time.sleep(5)
            continue
        if not resposta.get("ok"):
            time.sleep(3)
            continue

        for atualizacao in resposta.get("result", []):
            ultimo_update = atualizacao["update_id"] + 1

            callback = atualizacao.get("callback_query")
            if callback:
                chat_id = callback["message"]["chat"]["id"]
                message_id = callback["message"]["message_id"]
                data = callback.get("data", "")
                answer_callback(callback["id"])
                try:
                    processar_callback(chat_id, message_id, data)
                except Exception:
                    logging.exception("Erro ao processar callback do chat %s", chat_id)
                continue

            mensagem = atualizacao.get("message")
            if mensagem is None:
                continue

            chat_id = mensagem["chat"]["id"]
            texto = mensagem.get("text", "")
            if texto:
                try:
                    processar_mensagem(chat_id, texto)
                except Exception:
                    logging.exception("Erro ao processar mensagem do chat %s", chat_id)
                    enviar(chat_id, "⚠️ Ocorreu um erro durante a consulta. Tente novamente com /start.")


if __name__ == "__main__":
    iniciar_bot()
