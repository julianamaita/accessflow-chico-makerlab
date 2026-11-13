"""
Módulo de cálculo matemático.
Interpreta expressões faladas em português e retorna o resultado.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Mapa de palavras-chave para operadores
PALAVRAS_OPERADORES: dict[str, str] = {
    "mais": "+",
    "menos": "-",
    "vezes": "*",
    "multiplicado por": "*",
    "dividido por": "/",
    "dividido": "/",
    "sobre": "/",
    "por": "/",
}

# Palavras por extenso → dígitos
NUMEROS_EXTENSO: dict[str, str] = {
    "zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2",
    "três": "3", "tres": "3", "quatro": "4", "cinco": "5",
    "seis": "6", "sete": "7", "oito": "8", "nove": "9",
    "dez": "10", "onze": "11", "doze": "12", "treze": "13",
    "quatorze": "14", "catorze": "14", "quinze": "15",
    "dezesseis": "16", "dezessete": "17", "dezoito": "18", "dezenove": "19",
    "vinte": "20", "trinta": "30", "quarenta": "40", "cinquenta": "50",
    "sessenta": "60", "setenta": "70", "oitenta": "80", "noventa": "90",
    "cem": "100", "duzentos": "200", "trezentos": "300",
    "quatrocentos": "400", "quinhentos": "500",
    "mil": "1000",
}


class Calculadora:
    """Interpreta e calcula expressões matemáticas ditas em português."""

    def calcular(self, expressao: str) -> str:
        """
        Interpreta uma expressão em linguagem natural e calcula o resultado.

        Args:
            expressao: texto como "dez mais cinco" ou "10 + 5".

        Returns:
            String com o resultado ou mensagem de erro.
        """
        try:
            expr_normalizada = self._normalizar(expressao)
            logger.debug("Expressão normalizada: %s", expr_normalizada)

            # Valida se contém apenas caracteres seguros
            if not re.fullmatch(r"[\d\s\+\-\*\/\.\(\)]+", expr_normalizada):
                return "Não consegui interpretar essa expressão."

            resultado = eval(expr_normalizada)  # noqa: S307 — entrada já validada

            # Formata: sem decimal se for inteiro
            if isinstance(resultado, float) and resultado.is_integer():
                resultado = int(resultado)

            return f"O resultado é {resultado}"

        except ZeroDivisionError:
            return "Não é possível dividir por zero."
        except Exception as exc:
            logger.warning("Erro ao calcular '%s': %s", expressao, exc)
            return "Não consegui calcular essa expressão. Tente novamente."

    def _normalizar(self, texto: str) -> str:
        """
        Converte texto em português para expressão matemática.

        Args:
            texto: expressão em linguagem natural.

        Returns:
            String com operadores e números arábicos.
        """
        texto = texto.lower().strip()

        # Substitui operadores por extenso (ordem importa: "dividido por" antes de "por")
        for palavra, operador in PALAVRAS_OPERADORES.items():
            texto = texto.replace(palavra, f" {operador} ")

        # Substitui números por extenso
        for extenso, digito in NUMEROS_EXTENSO.items():
            texto = re.sub(rf"\b{extenso}\b", digito, texto)

        # Remove caracteres indesejados (exceto operadores e dígitos)
        texto = re.sub(r"[^\d\s\+\-\*\/\.\(\)]", "", texto)
        texto = re.sub(r"\s+", " ", texto).strip()

        return texto
