"""
api.py - Módulo de integração HTTP com a API pública da Tabela FIPE.

Este módulo é responsável por consumir os endpoints públicos da tabela FIPE
e retornar os dados estruturados para o restante da aplicação (Parte 1 do
projeto FipeCar_bot).

Endpoints consumidos (veículos / carros):
    GET /marcas
    GET /marcas/{codigo}/modelos
    GET /marcas/{codigo}/modelos/{codigo_modelo}/anos
    GET /marcas/{codigo}/modelos/{codigo_modelo}/anos/{codigo_ano}

Dependências:
    - httpx: cliente HTTP moderno (utilizado de forma síncrona neste módulo)
      Instale com: pip install httpx

Autor: FipeCar_bot
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de configuração base
# ---------------------------------------------------------------------------
BASE_URL_FIPE: str = "https://parallelum.com.br/fipe/api/v1/carros"
TIMEOUT_SECONDS: float = 30.0


def _requisicao_get(caminho: str) -> Optional[Any]:
    """
    Executa uma requisição GET genérica para a API FIPE com tratamento de erros.

    Centraliza a lógica de rede, tratamento de exceções do httpx e logging,
    evitando que falhas de rede ou instabilidade da API quebrem a aplicação.

    Args:
        caminho: Caminho do endpoint relativo à URL base
                 (exemplo: "/marcas").

    Returns:
        Os dados JSON decodificados da resposta, ou None em caso de falha.
    """
    url = f"{BASE_URL_FIPE}{caminho}"

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as cliente:
            resposta = cliente.get(url)
            # Lança exceção para status 4xx/5xx
            resposta.raise_for_status()
            return resposta.json()

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Erro HTTP %s ao acessar %s: %s",
            exc.response.status_code,
            url,
            exc,
        )
    except httpx.RequestError as exc:
        # Cobre falhas de rede, DNS, timeout, conexão recusada, etc.
        logger.error(
            "Erro de requisição (rede/instabilidade) ao acessar %s: %s",
            url,
            exc,
        )
    except ValueError as exc:
        # Falha ao decodificar o corpo da resposta como JSON
        logger.error(
            "Erro ao decodificar JSON da resposta de %s: %s",
            url,
            exc,
        )
    except Exception as exc:  # pylint: disable=broad-except
        # Rede de segurança para qualquer exceção não prevista
        logger.error(
            "Erro inesperado ao acessar %s: %s",
            url,
            exc,
        )

    return None


def obter_marcas() -> List[Dict[str, Any]]:
    """
    Busca a lista de marcas de carros disponíveis na tabela FIPE.

    Returns:
        Lista de dicionários contendo o código e o nome de cada marca.
        Exemplo: [{"codigo": "21", "nome": "Chevrolet"}, ...]
        Retorna uma lista vazia em caso de falha na requisição.
    """
    dados = _requisicao_get("/marcas")
    if dados is None:
        return []
    return dados


def obter_modelos(codigo_marca: str) -> List[Dict[str, Any]]:
    """
    Busca os modelos de uma marca específica.

    Args:
        codigo_marca: Código da marca selecionada.

    Returns:
        Lista de dicionários com os modelos da marca.
        Exemplo: [{"codigo": "211", "nome": "Onix"}, ...]
        Retorna uma lista vazia em caso de falha na requisição.
    """
    dados = _requisicao_get(f"/marcas/{codigo_marca}/modelos")
    if dados is None:
        return []

    # Neste endpoint a API FIPE retorna um dicionário com a chave "modelos"
    if isinstance(dados, dict):
        modelos = dados.get("modelos", [])
        return modelos if isinstance(modelos, list) else []

    return dados if isinstance(dados, list) else []


def obter_anos(codigo_marca: str, codigo_modelo: str) -> List[Dict[str, Any]]:
    """
    Busca os anos/versões disponíveis para um modelo específico.

    Args:
        codigo_marca: Código da marca.
        codigo_modelo: Código do modelo.

    Returns:
        Lista de dicionários com os anos/versões.
        Exemplo: [{"codigo": "2020-1", "nome": "2020 Gasolina"}, ...]
        Retorna uma lista vazia em caso de falha na requisição.
    """
    dados = _requisicao_get(
        f"/marcas/{codigo_marca}/modelos/{codigo_modelo}/anos"
    )
    if dados is None:
        return []
    return dados if isinstance(dados, list) else []


def obter_preco(
    codigo_marca: str,
    codigo_modelo: str,
    codigo_ano: str,
) -> Optional[Dict[str, Any]]:
    """
    Consulta o preço detalhado de um veículo específico.

    Args:
        codigo_marca: Código da marca.
        codigo_modelo: Código do modelo.
        codigo_ano: Código do ano/versão (exemplo: "2020-1").

    Returns:
        Dicionário com as principais informações formatadas:
            - Valor
            - Modelo
            - Marca
            - Ano do Modelo
            - Combustível
            - Código FIPE
            - Mês de Referência
        Retorna None em caso de falha na requisição.
    """
    dados = _requisicao_get(
        f"/marcas/{codigo_marca}/modelos/{codigo_modelo}/anos/{codigo_ano}"
    )
    if dados is None or not isinstance(dados, dict):
        return None

    return {
        "Valor": dados.get("Valor"),
        "Modelo": dados.get("Modelo"),
        "Marca": dados.get("Marca"),
        "Ano do Modelo": dados.get("AnoModelo"),
        "Combustível": dados.get("Combustivel"),
        "Código FIPE": dados.get("CódigoFIPE"),
        "Mês de Referência": dados.get("MêsReferencia"),
    }
#Teste de alteração