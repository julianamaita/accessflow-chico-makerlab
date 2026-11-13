"""
Monitor de iluminação (LDR) do Chico — AccessFlow / GS CitizenTech.

Problema: corredores e passagens acessíveis de clínicas e UBSs mal iluminados
são barreira para idosos e pessoas com baixa visão (risco de queda, dificuldade
de orientação). O robô monitora a luz do ambiente e age sozinho quando ela cai.

Fluxo:
  Arduino (LDR) --serial--> MonitorLuz (thread)
      -> suaviza leitura (média móvel) e converte para % da luz de referência
      -> classifica: ADEQUADA / BAIXA / CRITICA / FALHA (com histerese + persistência)
      -> devolve o modo ao Arduino (olhos e cabeça reagem)
      -> em mudança relevante: chama o callback (Chico fala o alerta gerado pela IA)
      -> grava leituras e ocorrências em CSV (data/)

Sem Arduino conectado, rode com SENSOR_PORTA=SIMULADO para demonstrar/testar.
"""

from __future__ import annotations

import csv
import logging
import math
import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
ARQ_LEITURAS = DATA_DIR / "leituras_luz.csv"
ARQ_OCORRENCIAS = DATA_DIR / "ocorrencias_luz.csv"
ARQ_CALIBRACAO = DATA_DIR / "calibracao_luz.txt"

BAUD = 115200

# Níveis de iluminação
ADEQUADA = "ADEQUADA"
BAIXA = "BAIXA"
CRITICA = "CRITICA"
FALHA = "FALHA"
SEM_DADOS = "SEM_DADOS"

MODO_ARDUINO = {ADEQUADA: "N", BAIXA: "A", CRITICA: "C", FALHA: "F", SEM_DADOS: "N"}

# Limites em % da luz de referência (a referência é calibrada no local)
LIMITE_BAIXA_PCT = 60.0
LIMITE_CRITICA_PCT = 30.0
HISTERESE_PCT = 5.0          # evita ficar trocando de estado na fronteira
PERSISTENCIA_S = 3.0         # o nível precisa se manter por X s antes de virar alerta
REFERENCIA_PADRAO = int(os.getenv("SENSOR_REFERENCIA", "55"))  # "luz normal" antes de calibrar (LDR + 1kΩ ≈ 55)
JANELA_MEDIA = 5             # média móvel de 5 leituras (~1 s)
INTERVALO_LOG_S = 2.0        # grava leitura no CSV a cada 2 s
FALHA_MIN, FALHA_MAX = 0, 1018  # leituras travadas nos extremos = fio solto/curto


@dataclass
class Ocorrencia:
    """Período em que a iluminação ficou abaixo do adequado."""

    nivel: str
    inicio: datetime
    pct_min: float
    fim: datetime | None = None
    mensagem_ia: str = ""

    @property
    def duracao_s(self) -> float:
        fim = self.fim or datetime.now()
        return (fim - self.inicio).total_seconds()


@dataclass
class EstadoLuz:
    bruto: int = 0
    pct: float = 0.0
    nivel: str = SEM_DADOS
    conectado: bool = False
    autonomo_arduino: bool = False
    atualizado_em: datetime | None = None
    historico: deque = field(default_factory=lambda: deque(maxlen=JANELA_MEDIA))


class MonitorLuz:
    """Lê o LDR via serial (ou simulação), classifica e dispara eventos."""

    def __init__(
        self,
        porta: str | None = None,
        local: str = "Corredor de acesso",
        ao_mudar_nivel: Callable[[str, str, "MonitorLuz"], None] | None = None,
    ) -> None:
        self.porta = porta if porta is not None else os.getenv("SENSOR_PORTA", "").strip()
        self.local = os.getenv("SENSOR_LOCAL", local)
        self.ao_mudar_nivel = ao_mudar_nivel
        self.simulado = self.porta.upper() == "SIMULADO"

        self.estado = EstadoLuz()
        self.referencia = self._carregar_calibracao()
        self.ocorrencia_atual: Ocorrencia | None = None

        self._nivel_candidato = SEM_DADOS
        self._candidato_desde = time.monotonic()
        self._ultimo_log = 0.0
        self._ultimo_envio = 0.0
        self._serial = None
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

        # Simulação: permite forçar cenários pela voz/teclado ("simular escuro")
        self._sim_alvo = 55.0
        self._sim_valor = 55.0
        self._sim_falha = False

        DATA_DIR.mkdir(exist_ok=True)
        self._garantir_csvs()

    # ------------------------------------------------------------------ #
    #  Ciclo de vida                                                       #
    # ------------------------------------------------------------------ #

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._loop, name="MonitorLuz", daemon=True)
        self._thread.start()
        logger.info("Monitor de luz iniciado (%s).", "simulado" if self.simulado else self.porta or "auto")

    def parar(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._fechar_serial()

    # ------------------------------------------------------------------ #
    #  Serial                                                              #
    # ------------------------------------------------------------------ #

    def _detectar_porta(self) -> str | None:
        """Procura uma porta com cara de Arduino (CH340, USB serial, ACM...)."""
        try:
            from serial.tools import list_ports
        except ImportError:
            logger.error("pyserial não instalado (pip install pyserial).")
            return None
        candidatos = []
        for p in list_ports.comports():
            desc = f"{p.description} {p.manufacturer or ''} {p.device}".lower()
            if any(k in desc for k in ("arduino", "ch340", "ch341", "usb serial", "usb-serial", "ttyacm", "ttyusb", "usbmodem", "usbserial", "wch")):
                candidatos.append(p.device)
        return candidatos[0] if candidatos else None

    def _abrir_serial(self) -> bool:
        import serial  # pyserial

        porta = self.porta or self._detectar_porta()
        if not porta:
            return False
        try:
            self._serial = serial.Serial(porta, BAUD, timeout=1)
            time.sleep(2)  # Uno reinicia ao abrir a porta
            self._serial.reset_input_buffer()
            self.porta_em_uso = porta
            logger.info("Arduino conectado em %s.", porta)
            return True
        except Exception as exc:  # porta ocupada, cabo solto, etc.
            logger.warning("Não abriu a porta %s: %s", porta, exc)
            self._serial = None
            return False

    def _fechar_serial(self) -> None:
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def _enviar_modo(self) -> None:
        if self.simulado or not self._serial:
            return
        try:
            self._serial.write(f"M:{MODO_ARDUINO[self.estado.nivel]}\n".encode())
        except Exception as exc:
            logger.warning("Falha ao enviar modo ao Arduino: %s", exc)
            self._desconectou()

    def _desconectou(self) -> None:
        self._fechar_serial()
        if self.estado.conectado:
            self.estado.conectado = False
            self._notificar("DESCONECTADO", self.estado.nivel)

    # ------------------------------------------------------------------ #
    #  Loop principal da thread                                            #
    # ------------------------------------------------------------------ #

    def _loop(self) -> None:
        aviso_sem_porta = False
        while not self._parar.is_set():
            if self.simulado:
                self.estado.conectado = True
                self._processar_leitura(self._ler_simulado())
                time.sleep(0.2)
                continue

            if not self._serial:
                if not self._abrir_serial():
                    if not aviso_sem_porta:
                        logger.warning("Arduino não encontrado. Tentando de novo a cada 3 s...")
                        aviso_sem_porta = True
                    self._parar.wait(3)
                    continue
                aviso_sem_porta = False
                self.estado.conectado = True
                self._notificar("CONECTADO", self.estado.nivel)

            try:
                linha = self._serial.readline().decode(errors="ignore").strip()
            except Exception as exc:
                logger.warning("Erro lendo serial: %s", exc)
                self._desconectou()
                continue

            if linha.startswith("L:"):
                try:
                    self._processar_leitura(int(linha[2:]))
                except ValueError:
                    continue
            elif linha == "S:AUTONOMO":
                self.estado.autonomo_arduino = True
            elif linha == "S:CONECTADO":
                self.estado.autonomo_arduino = False

            # Heartbeat: reenvia o modo 1x por segundo
            if time.monotonic() - self._ultimo_envio > 1.0:
                self._ultimo_envio = time.monotonic()
                self._enviar_modo()

    # ------------------------------------------------------------------ #
    #  Processamento / classificação                                       #
    # ------------------------------------------------------------------ #

    def _processar_leitura(self, bruto: int) -> None:
        with self._lock:
            est = self.estado
            est.historico.append(bruto)
            media = sum(est.historico) / len(est.historico)
            est.bruto = int(media)
            est.pct = max(0.0, min(150.0, 100.0 * media / max(self.referencia, 1)))
            est.atualizado_em = datetime.now()

            travado = len(est.historico) == est.historico.maxlen and all(
                v <= FALHA_MIN or v >= FALHA_MAX for v in est.historico
            )
            nivel_lido = FALHA if travado else self._classificar(est.pct, est.nivel)

        self._aplicar_persistencia(nivel_lido)

        agora = time.monotonic()
        if agora - self._ultimo_log >= INTERVALO_LOG_S:
            self._ultimo_log = agora
            self._gravar_leitura()

    def _classificar(self, pct: float, nivel_atual: str) -> str:
        """Classifica com histerese: para SAIR de um nível ruim precisa subir +5%."""
        h = HISTERESE_PCT
        lim_baixa = LIMITE_BAIXA_PCT + (h if nivel_atual in (BAIXA, CRITICA) else 0)
        lim_crit = LIMITE_CRITICA_PCT + (h if nivel_atual == CRITICA else 0)
        if pct < lim_crit:
            return CRITICA
        if pct < lim_baixa:
            return BAIXA
        return ADEQUADA

    def _aplicar_persistencia(self, nivel_lido: str) -> None:
        """Só confirma a mudança se o novo nível durar PERSISTENCIA_S (evita alarme por sombra rápida)."""
        agora = time.monotonic()
        if nivel_lido != self._nivel_candidato:
            self._nivel_candidato = nivel_lido
            self._candidato_desde = agora
            return
        espera = 0 if self.estado.nivel == SEM_DADOS else PERSISTENCIA_S
        if nivel_lido != self.estado.nivel and agora - self._candidato_desde >= espera:
            anterior = self.estado.nivel
            self.estado.nivel = nivel_lido
            self._atualizar_ocorrencia(anterior, nivel_lido)
            self._enviar_modo()
            self._notificar(nivel_lido, anterior)
        if self.ocorrencia_atual and self.estado.nivel in (BAIXA, CRITICA):
            self.ocorrencia_atual.pct_min = min(self.ocorrencia_atual.pct_min, self.estado.pct)
            if self.estado.nivel == CRITICA:
                self.ocorrencia_atual.nivel = CRITICA  # registra o pior nível do período

    def _atualizar_ocorrencia(self, anterior: str, novo: str) -> None:
        ruim = (BAIXA, CRITICA, FALHA)
        if novo in ruim and self.ocorrencia_atual is None:
            self.ocorrencia_atual = Ocorrencia(nivel=novo, inicio=datetime.now(), pct_min=self.estado.pct)
        elif novo == ADEQUADA and self.ocorrencia_atual is not None:
            self.ocorrencia_atual.fim = datetime.now()
            self._gravar_ocorrencia(self.ocorrencia_atual)
            self.ocorrencia_atual = None

    def _notificar(self, novo: str, anterior: str) -> None:
        logger.info("Iluminação: %s -> %s (%.0f%%)", anterior, novo, self.estado.pct)
        if self.ao_mudar_nivel:
            try:
                self.ao_mudar_nivel(novo, anterior, self)
            except Exception as exc:
                logger.error("Erro no callback do sensor: %s", exc)

    # ------------------------------------------------------------------ #
    #  Calibração                                                          #
    # ------------------------------------------------------------------ #

    def calibrar(self) -> int:
        """Usa a luz atual como referência de 'iluminação adequada' (100%)."""
        if not self.estado.historico:
            raise RuntimeError("Sem leituras do sensor para calibrar.")
        self.referencia = max(15, int(sum(self.estado.historico) / len(self.estado.historico)))
        ARQ_CALIBRACAO.write_text(str(self.referencia), encoding="utf-8")
        logger.info("Calibrado: referência = %d", self.referencia)
        return self.referencia

    def _carregar_calibracao(self) -> int:
        try:
            return max(15, int(ARQ_CALIBRACAO.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            return REFERENCIA_PADRAO

    # ------------------------------------------------------------------ #
    #  Persistência (CSV)                                                  #
    # ------------------------------------------------------------------ #

    def _garantir_csvs(self) -> None:
        if not ARQ_LEITURAS.exists():
            with ARQ_LEITURAS.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["timestamp", "local", "leitura_bruta", "luz_pct", "nivel"])
        if not ARQ_OCORRENCIAS.exists():
            with ARQ_OCORRENCIAS.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["inicio", "fim", "local", "nivel", "luz_min_pct", "duracao_s", "mensagem_ia"])

    def _gravar_leitura(self) -> None:
        e = self.estado
        try:
            with ARQ_LEITURAS.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    [datetime.now().isoformat(timespec="seconds"), self.local, e.bruto, f"{e.pct:.1f}", e.nivel]
                )
        except OSError as exc:
            logger.warning("Não gravou leitura: %s", exc)

    def _gravar_ocorrencia(self, oc: Ocorrencia) -> None:
        try:
            with ARQ_OCORRENCIAS.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    oc.inicio.isoformat(timespec="seconds"),
                    oc.fim.isoformat(timespec="seconds") if oc.fim else "",
                    self.local, oc.nivel, f"{oc.pct_min:.1f}", f"{oc.duracao_s:.0f}", oc.mensagem_ia,
                ])
        except OSError as exc:
            logger.warning("Não gravou ocorrência: %s", exc)

    def ler_ocorrencias(self, limite: int = 20) -> list[dict]:
        try:
            with ARQ_OCORRENCIAS.open(encoding="utf-8") as f:
                return list(csv.DictReader(f))[-limite:]
        except OSError:
            return []

    # ------------------------------------------------------------------ #
    #  Simulação (sem Arduino)                                             #
    # ------------------------------------------------------------------ #

    def simular(self, cenario: str) -> None:
        """Cenários: 'claro', 'penumbra', 'escuro', 'falha'."""
        self._sim_falha = cenario == "falha"
        self._sim_alvo = {"claro": 55, "penumbra": 28, "escuro": 10}.get(cenario, self._sim_alvo)

    def _ler_simulado(self) -> int:
        if self._sim_falha:
            return 0
        self._sim_valor += (self._sim_alvo - self._sim_valor) * 0.3
        ruido = random.gauss(0, 2) + 3 * math.sin(time.monotonic())
        return int(max(0, min(1023, self._sim_valor + ruido)))

    # ------------------------------------------------------------------ #
    #  Texto para o Chico                                                  #
    # ------------------------------------------------------------------ #

    def resumo_status(self) -> str:
        e = self.estado
        if not e.conectado:
            return "O sensor de luz não está conectado. Verifique o cabo USB do Arduino."
        if e.nivel == FALHA:
            return "O sensor de luz parece com defeito ou com fio solto. A leitura está travada no extremo."
        if e.nivel == SEM_DADOS:
            return "Ainda estou coletando as primeiras leituras do sensor."
        texto = {
            ADEQUADA: "a iluminação está adequada",
            BAIXA: "a iluminação está baixa, atenção",
            CRITICA: "a iluminação está crítica, a passagem está insegura",
        }[e.nivel]
        return f"No {self.local}, {texto}. Estou medindo {e.pct:.0f} por cento da luz de referência."


if __name__ == "__main__":
    # Teste rápido sem o Chico: python sensor_luz.py   (ou SENSOR_PORTA=SIMULADO python sensor_luz.py)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    def _cb(novo, anterior, mon):
        print(f">>> EVENTO: {anterior} -> {novo} | {mon.resumo_status()}")

    m = MonitorLuz(ao_mudar_nivel=_cb)
    m.iniciar()
    try:
        while True:
            e = m.estado
            print(f"bruto={e.bruto:4d}  luz={e.pct:5.1f}%  nivel={e.nivel:9s}  conectado={e.conectado}", end="\r")
            time.sleep(0.5)
    except KeyboardInterrupt:
        m.parar()
