"""
Módulo de cotações financeiras.
Usa a API gratuita AwesomeAPI para câmbio e CoinGecko para cripto.
"""

import logging

import requests

logger = logging.getLogger(__name__)

AWESOME_API_URL = "https://economia.awesomeapi.com.br/last"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


class Financas:
    """Busca cotações de câmbio e criptomoedas em tempo real."""

    def cotacao_dolar(self) -> str:
        """
        Retorna a cotação atual do dólar em reais.

        Returns:
            String com o valor do dólar ou mensagem de erro.
        """
        try:
            resp = requests.get(f"{AWESOME_API_URL}/USD-BRL", timeout=5)
            resp.raise_for_status()
            dados = resp.json()
            bid = float(dados["USDBRL"]["bid"])
            return f"O dólar está cotado a R$ {bid:.2f}."
        except requests.Timeout:
            logger.warning("Timeout ao buscar cotação do dólar.")
            return "Não consegui obter a cotação do dólar agora."
        except Exception as exc:
            logger.error("Erro ao buscar dólar: %s", exc)
            return "Erro ao buscar a cotação do dólar."

    def cotacao_bitcoin(self) -> str:
        """
        Retorna a cotação atual do Bitcoin em reais.

        Returns:
            String com o valor do Bitcoin ou mensagem de erro.
        """
        try:
            resp = requests.get(
                COINGECKO_URL,
                params={"ids": "bitcoin", "vs_currencies": "brl"},
                timeout=5,
            )
            resp.raise_for_status()
            dados = resp.json()
            preco = dados["bitcoin"]["brl"]
            return f"O Bitcoin está valendo R$ {preco:,.2f}."
        except requests.Timeout:
            logger.warning("Timeout ao buscar Bitcoin.")
            return "Não consegui obter o preço do Bitcoin agora."
        except Exception as exc:
            logger.error("Erro ao buscar Bitcoin: %s", exc)
            return "Erro ao buscar o preço do Bitcoin."
