"""
Camada de IA do monitor de iluminação.

Transforma a leitura do LDR em mensagens contextualizadas:
  - alerta falado quando a luz cai (considera nível, %, horário e local);
  - relatório das ocorrências para a equipe de manutenção.

Usa o Gemini quando disponível; se não houver chave/internet, cai em
mensagens-modelo (o robô nunca fica mudo por falta de IA).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ia_generativa import IAGenerativa

logger = logging.getLogger(__name__)

SISTEMA_ALERTA = (
    "Você é o Chico, robô assistente do AccessFlow, que monitora a acessibilidade "
    "de passagens em clínicas e unidades de saúde. Você recebe dados de um sensor de "
    "luminosidade e fala em voz alta com pacientes e funcionários. "
    "Responda em português brasileiro, no máximo 2 frases curtas, tom calmo e claro, "
    "sem emojis, sem markdown e sem números com casas decimais. "
    "Sempre inclua: o que está acontecendo, a quem afeta (ex.: idosos, pessoas com baixa visão) "
    "e uma ação concreta (ex.: acender luzes, acionar manutenção, andar com cuidado)."
)

SISTEMA_RELATORIO = (
    "Você é o Chico, robô do AccessFlow. Resuma ocorrências de iluminação inadequada "
    "para a equipe de manutenção de uma unidade de saúde. Português brasileiro, até 4 frases, "
    "texto para ser falado (sem markdown, sem listas). Destaque padrão de horário, pior ocorrência "
    "e uma recomendação."
)

FALLBACK = {
    "BAIXA": "Atenção: a iluminação no {local} está baixa. Pessoas com baixa visão podem ter dificuldade; "
             "recomendo acender as luzes.",
    "CRITICA": "Alerta: o {local} está muito escuro e inseguro para circulação, principalmente para idosos. "
               "Acionando a equipe de manutenção.",
    "ADEQUADA": "A iluminação do {local} voltou ao normal. Passagem liberada.",
    "FALHA": "Detectei uma falha no sensor de luz. Verifiquem a fiação do robô.",
    "DESCONECTADO": "Perdi a conexão com o sensor de luz. Verifiquem o cabo USB.",
    "CONECTADO": "Sensor de luz conectado. Monitoramento do {local} ativo.",
}


def _periodo_do_dia(hora: int) -> str:
    if 6 <= hora < 12:
        return "manhã"
    if 12 <= hora < 18:
        return "tarde"
    return "noite"


class AlertaLuz:
    def __init__(self, ia: "IAGenerativa") -> None:
        self.ia = ia

    def mensagem(self, nivel: str, anterior: str, local: str, pct: float) -> str:
        """Mensagem falada para uma mudança de estado do sensor."""
        base = FALLBACK.get(nivel, "").format(local=local)

        # Eventos técnicos não precisam de IA (resposta imediata e previsível)
        if nivel in ("FALHA", "DESCONECTADO", "CONECTADO"):
            return base

        agora = datetime.now()
        prompt = (
            f"Local monitorado: {local}.\n"
            f"Nível anterior: {anterior}. Nível atual: {nivel}.\n"
            f"Luz medida: {pct:.0f}% da iluminação de referência do local "
            f"(abaixo de 60% = baixa, abaixo de 30% = crítica).\n"
            f"Horário: {agora:%H:%M} ({_periodo_do_dia(agora.hour)}).\n"
            "Gere o aviso que o robô vai falar agora."
        )
        texto = self.ia.gerar(prompt, SISTEMA_ALERTA, max_chars=300)
        if texto:
            logger.info("Alerta gerado pela IA: %s", texto)
            return texto
        return base

    def relatorio(self, ocorrencias: list[dict], local: str) -> str:
        if not ocorrencias:
            return f"Não há ocorrências de iluminação registradas no {local}."

        linhas = [
            f"- início {o['inicio']}, nível {o['nivel']}, luz mínima {o['luz_min_pct']}%, duração {o['duracao_s']}s"
            for o in ocorrencias
        ]
        texto = self.ia.gerar(
            f"Local: {local}. Ocorrências registradas:\n" + "\n".join(linhas),
            SISTEMA_RELATORIO,
            max_chars=600,
        )
        if texto:
            return texto

        # Fallback: resumo estatístico simples
        luz = [o for o in ocorrencias if o["nivel"] in ("BAIXA", "CRITICA")]
        falhas = len(ocorrencias) - len(luz)
        partes = []
        if luz:
            criticas = sum(1 for o in luz if o["nivel"] == "CRITICA")
            pior = min(luz, key=lambda o: float(o["luz_min_pct"] or 100))
            partes.append(
                f"Registrei {len(luz)} ocorrência(s) de pouca luz no {local}, sendo {criticas} crítica(s). "
                f"A pior começou às {pior['inicio'][11:16]}, com {float(pior['luz_min_pct']):.0f} por cento da luz normal."
            )
        if falhas:
            partes.append(f"Também houve {falhas} falha(s) no sensor.")
        return " ".join(partes)
