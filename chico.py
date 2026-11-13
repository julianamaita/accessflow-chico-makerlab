"""
Módulo principal da assistente Chico.
Contém a classe Chico que orquestra todos os comandos.
"""

import logging
import os
import threading

import speech_recognition as sr

from agenda import Agenda
from alerta_luz import AlertaLuz
from calculadora import Calculadora
from clima import Clima
from financas import Financas
from ia_generativa import IAGenerativa
from face import ReconhecimentoFacial
from midia import Midia
from extras import Extras
from roteador import Roteador
from sensor_luz import ADEQUADA, BAIXA, CRITICA, FALHA, MonitorLuz
from sistema import Sistema
from tts import TTS

logger = logging.getLogger(__name__)

# Nome de ativação da assistente
NOME_ASSISTENTE = "chico"
ALIASES_ATIVACAO = {"chico", "tchico", "chicos"}  # variações de pronúncia


class Chico:
    """
    Assistente virtual Chico.

    Gerencia o ciclo de escuta → interpretação → execução de comandos de voz.
    Só executa ações após ser ativada pelo nome.
    """

    def __init__(self) -> None:
        """Inicializa todos os módulos e configura voz/microfone."""
        logger.info("Inicializando Chico...")

        # Reconhecimento de voz
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 0.8  # aguarda pausas de 0.8s
        self.recognizer.energy_threshold = 300

        # Síntese de voz (neural + fallback do sistema)
        self._tts = TTS()

        # Módulos de funcionalidade
        self.agenda = Agenda()
        self.calculadora = Calculadora()
        self.clima = Clima()
        self.financas = Financas()
        self.ia = IAGenerativa()
        self.face = ReconhecimentoFacial()
        self.midia = Midia()
        self.sistema = Sistema()
        # Extras cross-platform: detecta Windows/Mac no __init__ e faz retry
        self.extras = Extras()

        # Roteador por embeddings — remove a determinicidade dos if "palavra" in instrucao
        # Usa TF-IDF offline por padrao; para embeddings reais do Gemini, passe usar_gemini=True
        # (precisa de GEMINI_API_KEY e descomentar o bloco em roteador.py:_vetorizar)
        self.roteador = Roteador()

        # ── AccessFlow: sensor de luminosidade (LDR) + IA ──────────────
        # Thread separada lê o Arduino e chama _ao_mudar_luz sozinha,
        # sem depender de comando de voz (autonomia).
        self._lock_fala = threading.Lock()
        self.alerta_luz = AlertaLuz(self.ia)
        self.sensor = MonitorLuz(
            local=os.getenv("SENSOR_LOCAL", "corredor de acesso da clínica"),
            ao_mudar_nivel=self._ao_mudar_luz,
        )

        logger.info("Chico pronto!")

    # ------------------------------------------------------------------ #
    #  VOZ                                                                 #
    # ------------------------------------------------------------------ #

    def falar(self, texto: str) -> None:
        """Sintetiza voz e imprime o texto no console."""
        # Lock: o alerta automático do sensor e a resposta a um comando
        # nunca falam ao mesmo tempo
        with self._lock_fala:
            print(f"\n🤖 Chico: {texto}")
            self._tts.falar(texto)

    # ------------------------------------------------------------------ #
    #  SENSOR DE LUZ (autônomo)                                            #
    # ------------------------------------------------------------------ #

    def _ao_mudar_luz(self, novo: str, anterior: str, monitor: MonitorLuz) -> None:
        """Chamado pela thread do sensor quando o nível de iluminação muda."""
        # Ao ligar, "ficou adequada" não é notícia
        if novo == ADEQUADA and anterior not in (BAIXA, CRITICA, FALHA):
            return
        pct = monitor.estado.pct

        def _avisar() -> None:
            msg = self.alerta_luz.mensagem(novo, anterior, monitor.local, pct)
            if monitor.ocorrencia_atual and not monitor.ocorrencia_atual.mensagem_ia:
                monitor.ocorrencia_atual.mensagem_ia = msg
            self.falar(msg)

        # Gera/fala em outra thread para não travar a leitura da serial
        threading.Thread(target=_avisar, name="AlertaLuz", daemon=True).start()

    # ------------------------------------------------------------------ #
    #  ESCUTA                                                              #
    # ------------------------------------------------------------------ #

    def ouvir(self, prompt: str = "Ouvindo...") -> str:
        """
        Captura áudio do microfone e retorna o texto reconhecido.

        Args:
            prompt: mensagem exibida enquanto aguarda o usuário falar.

        Returns:
            Texto reconhecido em minúsculas, ou string vazia em caso de falha.
        """
        print(f"\n🎙️  {prompt}")
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=10)
            texto = self.recognizer.recognize_google(audio, language="pt-BR")
            texto = texto.lower().strip()
            print(f"   ✅ Reconhecido: '{texto}'")
            return texto
        except sr.WaitTimeoutError:
            logger.debug("Timeout ao aguardar fala.")
            return ""
        except sr.UnknownValueError:
            logger.debug("Fala não reconhecida.")
            return ""
        except sr.RequestError as exc:
            logger.error("Erro no serviço de reconhecimento: %s", exc)
            return ""

    def ouvir_ou_digitar(self, prompt: str = "Ouvindo...") -> str:
        """
        Permite que o usuário fale ou digite o comando (útil para testes).

        Returns:
            Comando em minúsculas.
        """
        digitado = input(f"\n⌨️  Digite o comando (Enter para usar voz): ").strip()
        if digitado:
            return digitado.lower()
        return self.ouvir(prompt)

    # ------------------------------------------------------------------ #
    #  ROTEAMENTO DE COMANDOS                                              #
    # ------------------------------------------------------------------ #

    def _ativada(self, comando: str) -> bool:
        """
        Verifica se o comando contém o nome de ativação da assistente.

        Args:
            comando: texto reconhecido pelo microfone.

        Returns:
            True se Chico foi chamado pelo nome.
        """
        return any(alias in comando for alias in ALIASES_ATIVACAO)

    def _extrair_instrucao(self, comando: str) -> str:
        """
        Remove o nome da assistente do comando, retornando só a instrução.

        Args:
            comando: texto completo do usuário.

        Returns:
            Instrução limpa sem o nome da assistente.
        """
        for alias in ALIASES_ATIVACAO:
            comando = comando.replace(alias, "").strip()
        return comando

    def _processar_comando(self, instrucao: str) -> bool:
        """
        Roteia a instrução para o módulo correto via embeddings.

        Fluxo:
          1) O roteador vetoriza a instrucao e acha o intent mais proximo (cosseno).
          2) Se o score ficar abaixo do limiar, cai no fallback da IA generativa.
          3) Cada intent mapeia para o mesmo handler de antes — so mudou o "if".
        Args:
            instrucao: comando já sem o nome da assistente.

        Returns:
            False se o usuário pediu para encerrar, True caso contrário.
        """
        # Roteamento por embeddings (TF-IDF offline por padrao)
        intent, score, _ = self.roteador.rotear(instrucao)
        logger.debug("Roteamento: '%s' -> %s (%.2f)", instrucao[:50], intent, score)

        # Se nao reconheceu nenhum intent, deixa a IA responder (fallback nao-deterministico)
        if intent is None:
            # Mas ainda checa saudacao/encerrar por fallback simples para nao gastar IA
            if not instrucao.strip():
                self.falar("Olá! Como posso ajudar?")
                return True
            self.falar("Não reconheci esse comando. Consultando a IA...")
            resposta = self.ia.perguntar(instrucao)
            self.falar(resposta)
            return True

        # ── AGENDA ──────────────────────────────────────────────────────
        if intent == "cadastrar_agenda":
            self.falar("Ok! Qual evento devo cadastrar?")
            evento = self.ouvir_ou_digitar("Aguardando o nome do evento...")
            if evento:
                self.agenda.cadastrar_evento(evento)
                self.falar(f"Evento '{evento}' cadastrado com sucesso!")
            else:
                self.falar("Não entendi o evento. Tente novamente.")

        elif intent == "ler_agenda":
            eventos = self.agenda.ler_eventos()
            if eventos:
                self.falar(f"Você tem {len(eventos)} evento(s) na agenda:")
                for i, ev in enumerate(eventos, 1):
                    self.falar(f"{i}: {ev}")
            else:
                self.falar("Sua agenda está vazia.")

        elif intent == "limpar_agenda":
            self.agenda.limpar_agenda()
            self.falar("Agenda limpa com sucesso!")

        # ── TEMPO / DATA ─────────────────────────────────────────────────
        elif intent == "hora":
            hora = self.sistema.hora_atual()
            self.falar(f"São {hora}.")

        elif intent == "data":
            dia = self.sistema.dia_atual()
            self.falar(f"Hoje é {dia}.")

        # ── CALCULAR ─────────────────────────────────────────────────────
        elif intent == "calcular":
            # Remove palavra "calcular/calcule" se existir, senao usa a frase toda (ex: "quanto e dez mais cinco")
            expressao = instrucao.replace("calcular", "").replace("calcule", "").strip()
            if not expressao:
                self.falar("Qual operação devo calcular?")
                expressao = self.ouvir_ou_digitar("Diga a operação...")
            # Se ainda nao tem operador, tenta usar a instrucao original completa
            if expressao == instrucao.replace("calcular", "").replace("calcule", "").strip() and "mais" not in expressao and "menos" not in expressao and "vezes" not in expressao:
                expressao = instrucao
            resultado = self.calculadora.calcular(expressao)
            self.falar(resultado)

        # ── RECONHECIMENTO FACIAL ─────────────────────────────────────────
        elif intent == "cadastrar_rosto":
            self.falar("Qual é o seu nome?")
            nome = self.ouvir_ou_digitar("Diga o nome para cadastrar...")
            if not nome:
                self.falar("Não entendi o nome. Tente novamente.")
            else:
                self.falar(f"Olhe para a câmera, {nome}. Vou tirar algumas fotos.")
                resultado = self.face.cadastrar(nome)
                self.falar(resultado)

        elif intent == "reconhecer_face":
            self.falar("Abrindo a câmera para reconhecimento facial...")
            nome = self.face.reconhecer()
            self.falar(f"Reconheci: {nome}")

        # ── IA GENERATIVA (Gemini) ────────────────────────────────────────
        elif intent == "ia_generativa":
            self.falar("Consultando a IA. Um momento...")
            resposta = self.ia.perguntar(instrucao)
            self.falar(resposta)

        # ── EXTRAS: CLIMA ─────────────────────────────────────────────────
        elif intent == "clima":
            cidade = self.clima.extrair_cidade(instrucao) or "São Paulo"
            self.falar(f"Verificando o clima em {cidade}...")
            previsao = self.clima.buscar_previsao(cidade)
            self.falar(previsao)

        # ── EXTRAS: FINANÇAS ──────────────────────────────────────────────
        elif intent == "dolar":
            cotacao = self.financas.cotacao_dolar()
            self.falar(cotacao)

        elif intent == "bitcoin":
            btc = self.financas.cotacao_bitcoin()
            self.falar(btc)

        # ── EXTRAS: MÍDIA ─────────────────────────────────────────────────
        elif intent == "controle_midia":
            # Decide a acao pelo conteudo da frase (pausar/proxima/anterior/continuar)
            low = instrucao.lower()
            if any(p in low for p in ("pausar", "pause", "parar")):
                self.falar(self.midia.pausar())
            elif any(p in low for p in ("proxima", "próxima", "pula", "pular")):
                self.falar(self.midia.proxima())
            elif any(p in low for p in ("anterior", "voltar", "volta")):
                self.falar(self.midia.anterior())
            else:
                self.falar(self.midia.continuar())

        elif intent == "tocar_musica":
            musica = (
                instrucao.replace("tocar", "")
                .replace("música", "")
                .replace("musica", "")
                .replace("no spotify", "")
                .replace("spotify", "")
                .strip()
            )
            if not musica:
                self.falar("Qual música devo tocar?")
                musica = self.ouvir_ou_digitar("Nome da música...")
            self.falar(self.midia.tocar_spotify(musica))

        elif intent == "pesquisar":
            termo = instrucao.replace("pesquisar", "").replace("pesquisa", "").replace("no google", "").replace("google", "").strip()
            if not termo:
                self.falar("O que devo pesquisar?")
                termo = self.ouvir_ou_digitar("O que pesquisar...")
            self.midia.pesquisar_google(termo)
            self.falar(f"Pesquisando '{termo}' no Google!")

        # ── EXTRAS ITEM 10 (cross-platform: detecta Windows/Mac e faz retry) ─
        elif intent == "volume":
            self.falar(self.extras.volume(instrucao))

        elif intent == "screenshot":
            self.falar(self.extras.screenshot())

        elif intent == "youtube":
            self.falar(self.extras.youtube(instrucao))

        elif intent == "portal_faculdade":
            self.falar(self.extras.portal_faculdade())

        # ── ACCESSFLOW: SENSOR DE LUZ ─────────────────────────────────────
        elif intent == "status_luz":
            self.falar(self.sensor.resumo_status())

        elif intent == "calibrar_luz":
            try:
                ref = self.sensor.calibrar()
                self.falar(
                    "Calibrado! A luz atual agora é a referência de iluminação adequada "
                    f"para o {self.sensor.local}."
                )
                logger.info("Referência de luz: %d", ref)
            except RuntimeError:
                self.falar("Não consegui calibrar: ainda não recebi leituras do sensor.")

        elif intent == "relatorio_luz":
            self.falar("Gerando o relatório de iluminação...")
            self.falar(self.alerta_luz.relatorio(self.sensor.ler_ocorrencias(), self.sensor.local))

        elif intent == "simular_luz":
            if not self.sensor.simulado:
                self.falar("A simulação só funciona com SENSOR_PORTA igual a SIMULADO no arquivo ponto env.")
            else:
                low = instrucao.lower()
                cenario = (
                    "falha" if "falha" in low
                    else "escuro" if "escur" in low
                    else "penumbra" if ("penumbra" in low or "pouca" in low)
                    else "claro"
                )
                self.sensor.simular(cenario)
                self.falar(f"Simulando ambiente {cenario}.")

        # ── SAUDAÇÕES ─────────────────────────────────────────────────────
        elif intent == "saudacao":
            self.falar("Olá! Como posso ajudar?")

        # ── ENCERRAR ──────────────────────────────────────────────────────
        elif intent == "encerrar":
            self.falar("Até logo! Encerrando o sistema.")
            return False  # sinal para parar o loop principal

        # ── FALLBACK (nao deveria cair aqui, ja tratado no inicio) ──────
        else:
            self.falar("Consultando a IA...")
            resposta = self.ia.perguntar(instrucao)
            self.falar(resposta)

        return True

    # ------------------------------------------------------------------ #
    #  LOOP PRINCIPAL                                                      #
    # ------------------------------------------------------------------ #

    def iniciar(self) -> None:
        """
        Inicia o loop principal da assistente.

        A assistente só processa comandos após reconhecer o próprio nome.
        Se o nome não for detectado, apenas imprime o texto reconhecido.
        """
        self.sensor.iniciar()
        self.falar("Sistema Chico inicializado. Monitorando a iluminação. Diga 'Chico' para ativar.")
        print("\n" + "=" * 60)
        print("  C.H.I.C.O. — Assistente Virtual")
        print("  Diga 'Chico' para ativar | 'sair' para encerrar")
        print("=" * 60)

        continuar = True
        while continuar:
            try:
                comando = self.ouvir_ou_digitar("Aguardando ativação ('Chico')...")

                if not comando:
                    continue  # nenhuma entrada, aguarda novamente

                if self._ativada(comando):
                    instrucao = self._extrair_instrucao(comando)

                    # Se só falou o nome sem instrução, pede o comando
                    if not instrucao:
                        self.falar("Sim? O que deseja?")
                        instrucao = self.ouvir_ou_digitar("Qual o comando?")

                    if instrucao:
                        continuar = self._processar_comando(instrucao)
                else:
                    # Nome não detectado → imprime sem executar ação
                    print(f"   [sem ativação] Texto reconhecido: '{comando}'")

            except KeyboardInterrupt:
                print("\n\n⚡ Interrompido pelo usuário.")
                self.falar("Encerrando. Até logo!")
                break

        self.sensor.parar()
