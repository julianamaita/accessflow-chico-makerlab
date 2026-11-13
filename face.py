"""
Reconhecimento facial com OpenCV (Haar + LBPH).

Fluxo simples:
  1. Cadastrar: a webcam tira várias fotos do rosto, alinhadas e com boa qualidade.
  2. Treinar: o OpenCV aprende quem é quem (com pequenas variações de cada foto).
  3. Reconhecer: a webcam identifica a pessoa, confirmando por vários frames.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Pastas sempre relativas a este arquivo (não dependem de onde o Python foi iniciado)
RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = RAIZ / "data"
PASTA_ROSTOS = PASTA_DADOS / "rostos"          # data/rostos/<nome>/foto.jpg
MODELO_PATH = PASTA_DADOS / "face_model.yml"
NOMES_PATH = PASTA_DADOS / "face_nomes.txt"

# Quantas fotos salvar por pessoa (60 dá uma boa margem para o LBPH generalizar)
FOTOS_POR_PESSOA = 60
TAMANHO_ROSTO = (200, 200)

# LBPH: número MENOR = mais parecido. Acima disso consideramos desconhecido.
LIMITE_CONFIANCA = 80

# Filtros de qualidade para não treinar/reconhecer com fotos ruins
NITIDEZ_MINIMA = 60.0          # variância do Laplaciano; abaixo disso está tremido/desfocado
BRILHO_MINIMO = 50             # média de pixel muito baixa = ambiente escuro
BRILHO_MAXIMO = 210            # média de pixel muito alta = estourado de luz
FRACAO_MINIMA_ROSTO = 0.15     # rosto deve ocupar ao menos 15% da largura do frame

# Quantos "votos" confiantes seguidos bastam para fechar o reconhecimento sozinho
VOTOS_PARA_CONFIRMAR = 15

# Dicas de pose mostradas durante o cadastro, para variar o ângulo capturado
DICAS_POSE = (
    "Olhe direto para a câmera",
    "Incline a cabeça levemente para a esquerda",
    "Incline a cabeça levemente para a direita",
    "Sorria naturalmente",
)

# Frases que o reconhecimento de voz costuma grudar antes do nome de verdade
# (ex.: "meu nome é Pedro" virava a pasta "meu_nome_e_pedro")
PADRAO_PREFIXO_NOME = re.compile(
    r"^\s*(meu nome (?:e|é)|eu me chamo|me chamo|pode me chamar de|"
    r"eu sou(?: o| a)?|sou(?: o| a)?)\s+",
    re.IGNORECASE,
)

# Nomes das janelas (sem travessão — o Cocoa do macOS fecha melhor assim)
JANELA_CADASTRO = "Chico Cadastro"
JANELA_RECONHECER = "Chico Reconhecer"


class ReconhecimentoFacial:
    """Detecta e reconhece rostos pela webcam."""

    def __init__(self) -> None:
        self._cv2 = None
        self._detector = None
        self._detector_olhos = None
        self._clahe = None
        self._reconhecedor = None
        self._nomes: list[str] = []
        # Janelas que já reportaram WND_PROP_VISIBLE > 0. No macOS o Cocoa
        # costuma devolver -1 o tempo todo, então só usamos o "clicou no X"
        # depois que a propriedade já funcionou pelo menos uma vez.
        self._janelas_visiveis: set[str] = set()
        self._iniciar_opencv()

    # ------------------------------------------------------------------ #
    #  Inicialização                                                       #
    # ------------------------------------------------------------------ #

    def _iniciar_opencv(self) -> None:
        """Carrega o OpenCV, os detectores Haar e o modelo treinado (se existir)."""
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV não instalado. Reconhecimento facial desativado.")
            return

        self._cv2 = cv2

        # alt2 tem menos falsos positivos que o "default"; se faltar, cai pro default
        caminho_alt2 = cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
        detector = cv2.CascadeClassifier(caminho_alt2)
        if detector.empty():
            caminho_default = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            detector = cv2.CascadeClassifier(caminho_default)
        self._detector = detector

        # Detector de olhos: usado só para alinhar o rosto antes de treinar/reconhecer
        caminho_olhos = cv2.data.haarcascades + "haarcascade_eye.xml"
        detector_olhos = cv2.CascadeClassifier(caminho_olhos)
        self._detector_olhos = None if detector_olhos.empty() else detector_olhos
        if self._detector_olhos is None:
            logger.warning("Cascade de olhos indisponível; seguindo sem alinhamento de rosto.")

        # CLAHE normaliza contraste local bem melhor que equalizeHist em luz irregular
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        self._carregar_modelo()

    def _carregar_modelo(self) -> None:
        """Lê o modelo LBPH e a lista de nomes do disco."""
        cv2 = self._cv2
        if cv2 is None or not hasattr(cv2, "face"):
            logger.warning("cv2.face indisponível. Instale opencv-contrib-python.")
            return

        if not MODELO_PATH.exists() or not NOMES_PATH.exists():
            logger.info("Nenhum modelo treinado ainda. Use 'cadastrar rosto'.")
            return

        reconhecedor = cv2.face.LBPHFaceRecognizer_create()
        reconhecedor.read(str(MODELO_PATH))
        self._reconhecedor = reconhecedor
        self._nomes = [
            linha.strip()
            for linha in NOMES_PATH.read_text(encoding="utf-8").splitlines()
            if linha.strip()
        ]
        logger.info("Modelo facial carregado: %s", self._nomes)

    # ------------------------------------------------------------------ #
    #  Cadastro (captura fotos)                                            #
    # ------------------------------------------------------------------ #

    def cadastrar(self, nome: str) -> str:
        """
        Abre a webcam, tira FOTOS_POR_PESSOA fotos do rosto e treina o modelo.

        Só salva frames com boa nitidez, boa iluminação e rosto grande o
        bastante — evita treinar o modelo com fotos ruins. Se a pessoa já
        tiver fotos cadastradas, as novas são adicionadas (não sobrescreve).

        Teclas na janela da câmera:
          q  → cancelar
        """
        if self._cv2 is None:
            return "OpenCV não instalado. Reconhecimento facial indisponível."

        nome_limpo = self._limpar_nome(nome)
        if not nome_limpo:
            return "Preciso de um nome válido para cadastrar o rosto."

        pasta = PASTA_ROSTOS / nome_limpo
        pasta.mkdir(parents=True, exist_ok=True)

        indice_inicial = self._proximo_indice(pasta)

        cap = self._abrir_camera()
        if cap is None:
            return "Não consegui acessar a câmera. Verifique a permissão no macOS."

        cv2 = self._cv2
        salvas = 0
        intervalo = 8   # espera alguns frames entre uma foto e outra
        espera = 0

        print(f"\n Olhe para a câmera. Vou tirar {FOTOS_POR_PESSOA} fotos de '{nome_limpo}'.")
        print("   Pressione 'q' para cancelar (ou feche a janela).")

        self._criar_janela(JANELA_CADASTRO)
        try:
            while salvas < FOTOS_POR_PESSOA:
                ok, frame = cap.read()
                if not ok:
                    break

                # Espelha a imagem (fica mais natural, como um espelho)
                frame = cv2.flip(frame, 1)
                cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                rosto = self._rosto_principal(cinza)

                if rosto is not None:
                    x, y, w, h = rosto
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                    amostra = self._preparar_amostra(cinza, x, y, w, h)
                    problema = self._qualidade(amostra, w, cinza.shape[1]) if amostra is not None else "Ajuste o rosto"

                    if problema is None and espera <= 0:
                        arquivo = pasta / f"{indice_inicial + salvas:03d}.jpg"
                        cv2.imwrite(str(arquivo), amostra)
                        salvas += 1
                        espera = intervalo
                        logger.info("Foto %s/%s salva.", salvas, FOTOS_POR_PESSOA)

                    espera = max(0, espera - 1)

                    dica = problema or DICAS_POSE[min(salvas // max(1, FOTOS_POR_PESSOA // len(DICAS_POSE)), len(DICAS_POSE) - 1)]
                    cor_dica = (0, 0, 255) if problema else (0, 255, 255)
                    cv2.putText(frame, dica, (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, cor_dica, 2)
                else:
                    cv2.putText(frame, "Nenhum rosto encontrado", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                cv2.putText(
                    frame,
                    f"{salvas}/{FOTOS_POR_PESSOA}  {nome_limpo}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow(JANELA_CADASTRO, frame)
                if self._pediu_para_fechar(JANELA_CADASTRO):
                    logger.info(
                        "Cadastro interrompido na foto %s/%s.",
                        salvas,
                        FOTOS_POR_PESSOA,
                    )
                    break
        finally:
            # Sempre libera a câmera e força o fechamento da janela (bug do OpenCV no Mac)
            self._fechar_camera(cap, JANELA_CADASTRO)

        if salvas == 0:
            return "Não detectei nenhum rosto com boa qualidade. Tente de novo com mais luz, mais perto e de frente para a câmera."

        # Treina de novo com TODOS os rostos cadastrados
        treino = self.treinar()
        return f"Cadastrei {salvas} fotos de {nome_limpo}. {treino}"

    # ------------------------------------------------------------------ #
    #  Treino                                                              #
    # ------------------------------------------------------------------ #

    def treinar(self) -> str:
        """Lê as fotos em data/rostos/ e gera o modelo LBPH."""
        cv2 = self._cv2
        if cv2 is None or not hasattr(cv2, "face"):
            return "Não foi possível treinar: opencv-contrib-python não está disponível."

        imagens: list = []
        labels: list[int] = []
        nomes: list[str] = []

        PASTA_ROSTOS.mkdir(parents=True, exist_ok=True)
        pastas = sorted(p for p in PASTA_ROSTOS.iterdir() if p.is_dir())

        for indice, pasta in enumerate(pastas):
            fotos = list(pasta.glob("*.jpg"))
            if not fotos:
                continue
            nomes.append(pasta.name)
            for foto in fotos:
                img = cv2.imread(str(foto), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                for variante in self._gerar_variantes(img):
                    imagens.append(variante)
                    labels.append(indice)

        if not imagens:
            return "Não há fotos para treinar. Cadastre um rosto primeiro."

        reconhecedor = cv2.face.LBPHFaceRecognizer_create()
        reconhecedor.train(imagens, np.array(labels, dtype=np.int32))

        PASTA_DADOS.mkdir(parents=True, exist_ok=True)
        reconhecedor.write(str(MODELO_PATH))
        NOMES_PATH.write_text("\n".join(nomes) + "\n", encoding="utf-8")

        self._reconhecedor = reconhecedor
        self._nomes = nomes
        logger.info("Modelo treinado com %s amostra(s) de %s.", len(imagens), nomes)
        return f"Modelo treinado com {len(nomes)} pessoa(s): {', '.join(nomes)}."

    def _gerar_variantes(self, img: np.ndarray) -> list:
        """
        Gera pequenas variações (rotação leve + brilho) de cada foto original.

        Com poucas fotos por pessoa, essas variações ajudam o LBPH a não
        depender de um ângulo/iluminação único — melhora a generalização
        sem precisar pedir mais fotos ao usuário.
        """
        cv2 = self._cv2
        variantes = [img]

        centro = (img.shape[1] / 2, img.shape[0] / 2)
        for angulo in (-6, 6):
            matriz = cv2.getRotationMatrix2D(centro, angulo, 1.0)
            variantes.append(cv2.warpAffine(img, matriz, (img.shape[1], img.shape[0])))

        variantes.append(cv2.convertScaleAbs(img, alpha=1.15, beta=10))   # um pouco mais claro
        variantes.append(cv2.convertScaleAbs(img, alpha=0.85, beta=-10))  # um pouco mais escuro

        return variantes

    # ------------------------------------------------------------------ #
    #  Reconhecimento                                                      #
    # ------------------------------------------------------------------ #

    def reconhecer(self) -> str:
        """
        Abre a webcam e tenta identificar o rosto.

        Em vez de confiar só no frame em que a câmera foi fechada, acumula
        os reconhecimentos confiantes de vários frames e decide pelo mais
        votado — evita que um frame ruim isolado dê um resultado errado.
        Fecha sozinho depois de confirmar a mesma pessoa várias vezes
        seguidas, ou ao apertar 'q'.
        """
        if self._cv2 is None:
            return "OpenCV não instalado. Reconhecimento facial indisponível."

        # Recarrega o modelo (caso alguém tenha cadastrado agora)
        self._carregar_modelo()

        cap = self._abrir_camera()
        if cap is None:
            return "Não consegui acessar a câmera. Verifique a permissão no macOS."

        cv2 = self._cv2
        treinado = bool(self._reconhecedor and self._nomes)
        votos: Counter = Counter()
        distancias: dict[str, list[float]] = defaultdict(list)
        algum_rosto_detectado = False

        print("\n Câmera aberta. Pressione 'q' para encerrar (ou feche a janela).")

        self._criar_janela(JANELA_RECONHECER)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                frame = cv2.flip(frame, 1)
                cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                rostos = list(self._encontrar_rostos(cinza))
                idx_principal = (
                    max(range(len(rostos)), key=lambda i: rostos[i][2] * rostos[i][3])
                    if rostos else None
                )

                for i, (x, y, w, h) in enumerate(rostos):
                    algum_rosto_detectado = True
                    amostra = self._preparar_amostra(cinza, x, y, w, h)
                    problema = self._qualidade(amostra, w, cinza.shape[1]) if amostra is not None else "Ajuste o rosto"

                    if problema is not None:
                        texto, cor = problema, (0, 0, 255)
                    elif treinado:
                        label, distancia = self._reconhecedor.predict(amostra)
                        confianca_pct = max(0, round(100 - distancia))
                        if distancia < LIMITE_CONFIANCA and 0 <= label < len(self._nomes):
                            nome_atual = self._nomes[label]
                            texto, cor = f"{nome_atual} ({confianca_pct}%)", (0, 255, 0)
                            if i == idx_principal:
                                votos[nome_atual] += 1
                                distancias[nome_atual].append(distancia)
                        else:
                            texto, cor = "Desconhecido", (0, 0, 255)
                    else:
                        texto, cor = "não treinado", (0, 165, 255)

                    cv2.rectangle(frame, (x, y), (x + w, y + h), cor, 2)
                    cv2.putText(frame, texto, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor, 2)

                cv2.imshow(JANELA_RECONHECER, frame)
                if self._pediu_para_fechar(JANELA_RECONHECER):
                    break
                if votos and votos.most_common(1)[0][1] >= VOTOS_PARA_CONFIRMAR:
                    break
        finally:
            self._fechar_camera(cap, JANELA_RECONHECER)

        if votos:
            nome_final, qtd = votos.most_common(1)[0]
            media = sum(distancias[nome_final]) / len(distancias[nome_final])
            resultado = nome_final
            logger.info("Reconhecido '%s' com %d voto(s), distância média %.1f.", nome_final, qtd, media)
        elif not algum_rosto_detectado:
            resultado = "Nenhum rosto detectado."
        elif treinado:
            resultado = "Desconhecido"
        else:
            resultado = "Rosto detectado. Cadastre um rosto antes de reconhecer."

        logger.info("Reconhecimento facial: %s", resultado)
        return resultado

    # ------------------------------------------------------------------ #
    #  Qualidade e alinhamento da amostra                                  #
    # ------------------------------------------------------------------ #

    def _preparar_amostra(self, cinza_frame: np.ndarray, x: int, y: int, w: int, h: int):
        """
        Recorta o rosto, alinha pelos olhos e normaliza o contraste (CLAHE).

        Alinhar deixa a linha entre os dois olhos na horizontal — reduz
        bastante o erro do LBPH quando a cabeça está levemente inclinada.
        Sem os dois olhos detectados, usa o recorte reto (sem rotação).
        """
        cv2 = self._cv2
        origem = cinza_frame

        if self._detector_olhos is not None:
            roi = cinza_frame[y:y + h, x:x + w]
            tam_min = (max(1, int(w * 0.15)), max(1, int(h * 0.15)))
            olhos = self._detector_olhos.detectMultiScale(
                roi, scaleFactor=1.1, minNeighbors=8, minSize=tam_min
            )
            if len(olhos) >= 2:
                maiores = sorted(olhos, key=lambda o: o[2] * o[3], reverse=True)[:2]
                maiores = sorted(maiores, key=lambda o: o[0])
                (ex1, ey1, ew1, eh1), (ex2, ey2, ew2, eh2) = maiores
                c1 = (x + ex1 + ew1 / 2, y + ey1 + eh1 / 2)
                c2 = (x + ex2 + ew2 / 2, y + ey2 + eh2 / 2)
                angulo = float(np.degrees(np.arctan2(c2[1] - c1[1], c2[0] - c1[0])))
                centro_rosto = (x + w / 2, y + h / 2)
                matriz = cv2.getRotationMatrix2D(centro_rosto, angulo, 1.0)
                origem = cv2.warpAffine(
                    cinza_frame, matriz, (cinza_frame.shape[1], cinza_frame.shape[0])
                )

        recorte = origem[y:y + h, x:x + w]
        if recorte.size == 0:
            return None

        recorte = cv2.resize(recorte, TAMANHO_ROSTO)
        return self._clahe.apply(recorte)

    def _qualidade(self, amostra: np.ndarray, largura_rosto: int, largura_frame: int) -> str | None:
        """
        Verifica se a amostra tem qualidade suficiente para salvar/reconhecer.

        Returns:
            None se estiver tudo certo, ou uma dica curta do que corrigir.
        """
        if largura_frame > 0 and largura_rosto < largura_frame * FRACAO_MINIMA_ROSTO:
            return "Aproxime-se da câmera"

        brilho = float(amostra.mean())
        if brilho < BRILHO_MINIMO:
            return "Ambiente muito escuro"
        if brilho > BRILHO_MAXIMO:
            return "Muita luz/reflexo"

        nitidez = float(self._cv2.Laplacian(amostra, self._cv2.CV_64F).var())
        if nitidez < NITIDEZ_MINIMA:
            return "Fique parado (imagem tremida)"

        return None

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _abrir_camera(self):
        """Abre a webcam padrão. Retorna None se falhar."""
        cap = self._cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.error("Não foi possível abrir a webcam.")
            cap.release()
            return None
        return cap

    def _criar_janela(self, nome: str) -> None:
        """Cria a janela antes do imshow para poder detectá-la ao fechar."""
        self._janelas_visiveis.discard(nome)
        self._cv2.namedWindow(nome, self._cv2.WINDOW_NORMAL)

    def _pediu_para_fechar(self, nome_janela: str) -> bool:
        """True se apertou q/ESC, ou se clicou no X (quando o backend reporta isso).

        No macOS o backend Cocoa do OpenCV devolve -1 em WND_PROP_VISIBLE
        mesmo com a janela aberta. Tratar -1 como "fechou" encerrava o
        cadastro no primeiro frame — só 1 foto era salva das 60.
        """
        # 30 ms: dá tempo do Cocoa pintar a janela e deixa o loop ~30 fps
        tecla = self._cv2.waitKey(30) & 0xFF
        if tecla in (ord("q"), 27):
            return True
        try:
            visivel = self._cv2.getWindowProperty(nome_janela, self._cv2.WND_PROP_VISIBLE)
        except Exception:
            return False
        if visivel > 0:
            self._janelas_visiveis.add(nome_janela)
            return False
        # Só considera "clicou no X" se a janela já chegou a ficar visível.
        # Se o backend só devolve -1 (macOS), ignoramos e o usuário sai com q.
        return nome_janela in self._janelas_visiveis

    def _fechar_camera(self, cap, nome_janela: str) -> None:
        """
        Libera a webcam e fecha a janela de verdade.

        No macOS, destroyAllWindows() sozinho não basta: o Cocoa só
        processa o fechamento depois de alguns waitKey().
        """
        cv2 = self._cv2
        self._janelas_visiveis.discard(nome_janela)
        if cap is not None:
            cap.release()
        if cv2 is None:
            return
        try:
            cv2.destroyWindow(nome_janela)
        except cv2.error:
            pass
        cv2.destroyAllWindows()
        for _ in range(10):
            cv2.waitKey(1)

    def _encontrar_rostos(self, cinza):
        """Devolve as caixas (x, y, w, h) de todos os rostos no frame em cinza."""
        return self._detector.detectMultiScale(
            cinza,
            scaleFactor=1.15,
            minNeighbors=6,
            minSize=(80, 80),
        )

    def _rosto_principal(self, cinza):
        """Devolve só a maior caixa de rosto encontrada (ou None)."""
        rostos = list(self._encontrar_rostos(cinza))
        if not rostos:
            return None
        return max(rostos, key=lambda r: r[2] * r[3])

    @staticmethod
    def _proximo_indice(pasta: Path) -> int:
        """Próximo número de arquivo livre em uma pasta de rostos (para não sobrescrever fotos antigas)."""
        indices = [int(p.stem) for p in pasta.glob("*.jpg") if p.stem.isdigit()]
        return max(indices) + 1 if indices else 0

    @staticmethod
    def _limpar_nome(nome: str) -> str:
        """
        Extrai o nome de uma frase falada e deixa pronto para virar pasta.

        Remove prefixos comuns que o reconhecimento de voz gruda junto com
        o nome (ex.: "meu nome é Pedro" → "pedro", não "meu_nome_e_pedro").
        """
        texto = nome.lower().strip()
        texto = PADRAO_PREFIXO_NOME.sub("", texto)
        limpo = re.sub(r"[^a-z0-9áàâãéêíóôõúç\s-]", "", texto)
        return re.sub(r"\s+", "_", limpo).strip("_")


if __name__ == "__main__":
    # Uso direto, sem a assistente:
    #   python face.py cadastrar Maria
    #   python face.py reconhecer
    import sys

    face = ReconhecimentoFacial()
    if len(sys.argv) >= 3 and sys.argv[1] == "cadastrar":
        print(face.cadastrar(" ".join(sys.argv[2:])))
    elif len(sys.argv) >= 2 and sys.argv[1] == "treinar":
        print(face.treinar())
    else:
        print(face.reconhecer())
