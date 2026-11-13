"""
Projeto C.H.I.C.O. - CP4 2º Semestre FIAP
Assistente virtual por reconhecimento de voz.

Autores: [Nomes do grupo]
Data de entrega: 31/08/2026
"""

import logging
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env (GEMINI_API_KEY etc.)
load_dotenv()

from chico import Chico

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("chico.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

if __name__ == "__main__":
    assistente = Chico()
    assistente.iniciar()
