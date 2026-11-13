"""
Módulo de informações do sistema.
Fornece hora atual, data e outras informações do SO.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Nomes dos dias e meses em português
DIAS_SEMANA = {
    0: "segunda-feira", 1: "terça-feira", 2: "quarta-feira",
    3: "quinta-feira", 4: "sexta-feira", 5: "sábado", 6: "domingo",
}

MESES = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


class Sistema:
    """Fornece informações sobre hora e data em português."""

    def hora_atual(self) -> str:
        """
        Retorna a hora atual formatada para leitura em voz.

        Returns:
            String como 'quatorze horas e trinta minutos'.
        """
        agora = datetime.now()
        hora = agora.strftime("%H")
        minuto = agora.strftime("%M")
        texto = f"{hora} horas"
        if minuto != "00":
            texto += f" e {minuto} minutos"
        logger.debug("Hora consultada: %s", texto)
        return texto

    def dia_atual(self) -> str:
        """
        Retorna o dia atual formatado por extenso.

        Returns:
            String como 'segunda-feira, 24 de agosto de 2026'.
        """
        agora = datetime.now()
        dia_semana = DIAS_SEMANA[agora.weekday()]
        mes_nome = MESES[agora.month]
        texto = f"{dia_semana}, {agora.day} de {mes_nome} de {agora.year}"
        logger.debug("Data consultada: %s", texto)
        return texto
