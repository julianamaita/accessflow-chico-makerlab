"""
Módulo de previsão do tempo.
Usa a API gratuita Open-Meteo (sem necessidade de chave).
Geocoding via Open-Meteo também (gratuito).
"""

import logging
import re

import requests

logger = logging.getLogger(__name__)

# Cidades mencionadas com frequência no comando
CIDADES_CONHECIDAS = [
    "são paulo", "rio de janeiro", "belo horizonte", "brasília",
    "curitiba", "porto alegre", "salvador", "fortaleza", "manaus",
    "recife", "campinas", "guarulhos", "osasco",
]

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Códigos WMO de clima → descrição
DESCRICAO_CLIMA: dict[int, str] = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado",
    3: "nublado", 45: "nevoeiro", 51: "garoa leve", 53: "garoa moderada",
    61: "chuva leve", 63: "chuva moderada", 65: "chuva forte",
    71: "neve leve", 80: "chuviscos", 95: "tempestade",
}


class Clima:
    """Busca previsão do tempo usando APIs gratuitas."""

    def extrair_cidade(self, instrucao: str) -> str:
        """
        Tenta identificar o nome de uma cidade na instrução.

        Args:
            instrucao: texto do comando do usuário.

        Returns:
            Nome da cidade encontrada ou string vazia.
        """
        instrucao_lower = instrucao.lower()
        for cidade in CIDADES_CONHECIDAS:
            if cidade in instrucao_lower:
                return cidade.title()

        # Tenta extrair após 'em' ou 'para'
        match = re.search(r"(?:em|para|de)\s+([a-záéíóúâêîôûãõç\s]+)", instrucao_lower)
        if match:
            candidato = match.group(1).strip()
            # Remove palavras de comando
            for remover in ["hoje", "agora", "amanhã", "essa semana"]:
                candidato = candidato.replace(remover, "").strip()
            if candidato:
                return candidato.title()
        return ""

    def buscar_previsao(self, cidade: str = "São Paulo") -> str:
        """
        Busca a previsão do tempo atual para uma cidade.

        Args:
            cidade: nome da cidade.

        Returns:
            String descritiva com temperatura e condição climática.
        """
        try:
            # Geocoding: nome da cidade → coordenadas
            geo_resp = requests.get(
                GEOCODING_URL,
                params={"name": cidade, "count": 1, "language": "pt", "format": "json"},
                timeout=5,
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                return f"Não encontrei a cidade {cidade}."

            local = geo_data["results"][0]
            lat, lon = local["latitude"], local["longitude"]
            nome_local = local.get("name", cidade)

            # Previsão atual
            meteo_resp = requests.get(
                METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weathercode,windspeed_10m",
                    "timezone": "America/Sao_Paulo",
                },
                timeout=5,
            )
            meteo_resp.raise_for_status()
            meteo_data = meteo_resp.json()

            atual = meteo_data["current"]
            temp = atual["temperature_2m"]
            codigo = atual["weathercode"]
            vento = atual["windspeed_10m"]
            condicao = DESCRICAO_CLIMA.get(codigo, "condição desconhecida")

            return (
                f"Em {nome_local}: {temp}°C, {condicao}, "
                f"vento de {vento} km/h."
            )

        except requests.Timeout:
            logger.warning("Timeout ao buscar clima para %s.", cidade)
            return "Não consegui obter o clima agora. Verifique sua conexão."
        except Exception as exc:
            logger.error("Erro ao buscar clima: %s", exc)
            return "Erro ao buscar a previsão do tempo."
