"""
Módulo de gerenciamento de agenda.
Responsável por cadastrar, ler e limpar eventos no arquivo agenda.txt.
"""

import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

AGENDA_PATH = Path("data") / "agenda.txt"


class Agenda:
    """Gerencia eventos em arquivo de texto local (agenda.txt)."""

    def __init__(self) -> None:
        """Garante que o diretório e o arquivo existam."""
        AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not AGENDA_PATH.exists():
            AGENDA_PATH.touch()
            logger.info("Arquivo agenda.txt criado em %s", AGENDA_PATH)

    def cadastrar_evento(self, evento: str) -> None:
        """
        Adiciona um evento à agenda com timestamp.

        Args:
            evento: descrição do evento a ser cadastrado.
        """
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        linha = f"[{timestamp}] {evento}\n"
        with open(AGENDA_PATH, "a", encoding="utf-8") as arquivo:
            arquivo.write(linha)
        logger.info("Evento cadastrado: %s", evento)

    def ler_eventos(self) -> list[str]:
        """
        Lê todos os eventos cadastrados na agenda.

        Returns:
            Lista de eventos (strings), vazia se não houver nenhum.
        """
        with open(AGENDA_PATH, "r", encoding="utf-8") as arquivo:
            eventos = [linha.strip() for linha in arquivo if linha.strip()]
        logger.info("%d evento(s) lido(s) da agenda.", len(eventos))
        return eventos

    def limpar_agenda(self) -> None:
        """Apaga o conteúdo da agenda sem excluir o arquivo."""
        with open(AGENDA_PATH, "w", encoding="utf-8") as arquivo:
            arquivo.write("")
        logger.info("Agenda limpa.")
