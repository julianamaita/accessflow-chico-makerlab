"""
Roteador por embeddings — remove a determinicidade dos comandos do Chico.

Antes: if "calcul" in instrucao / if "horas" in instrucao  (quebra com sinonimos).
Agora: a frase do usuario vira vetor e compara (cosseno) com exemplos de cada intent.

Dois modos:
  1) TF-IDF offline (padrao) — funciona sem internet, instantaneo, ja vem com sklearn.
  2) Gemini embeddings (opcional) — troca uma linha em _vetorizar para usar text-embedding-004.

Como funciona:
  - Cada intent tem 5-8 frases exemplo (INTENTS_EXEMPLOS).
  - Na inicializacao, todas viram vetores e sao indexadas.
  - Em rotear(), a instrucao do usuario vira vetor, calcula similaridade com cada intent,
    retorna o intent vencedor se acima do limiar, senao None (vai pra IA generativa).
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata

import numpy as np

logger = logging.getLogger(__name__)

# Limiar de similaridade cosseno para aceitar o intent (0 a 1).
# Abaixo disso, consideramos que nao e nenhum intent conhecido e deixamos a IA responder.
LIMIAR_SIMILARIDADE = 0.25

# Frases exemplo por intent — quanto mais variada, melhor o roteamento pega sinonimos.
# Estas frases NUNCA sao faladas pelo usuario, servem so como "centroides" do intent.
INTENTS_EXEMPLOS: dict[str, list[str]] = {
    "cadastrar_agenda": [
        "cadastrar evento na agenda",
        "adicionar compromisso na agenda",
        "marca um lembrete pra mim",
        "anotar evento",
        "salvar na agenda",
        "coloca na minha agenda",
        "marcar compromisso",
    ],
    "ler_agenda": [
        "ler agenda",
        "mostrar meus compromissos",
        "quais eventos tenho",
        "abre a agenda",
        "o que tenho marcado",
        "ver agenda",
    ],
    "limpar_agenda": [
        "limpar agenda",
        "apagar todos os eventos",
        "esvaziar agenda",
        "deletar compromissos",
        "zerar a agenda",
    ],
    "hora": [
        "que horas sao",
        "me diz a hora atual",
        "qual e o horario agora",
        "hora certa",
        "que horas sao agora",
    ],
    "data": [
        "que dia e hoje",
        "qual a data de hoje",
        "me diz o dia da semana",
        "hoje e que dia",
        "data atual",
    ],
    "calcular": [
        "calcular dez mais cinco",
        "quanto e cinco vezes tres",
        "faz a conta de vinte dividido por quatro",
        "resolve essa operacao matematica",
        "calcule pra mim",
        "quanto da essa conta",
    ],
    "cadastrar_rosto": [
        "cadastrar rosto",
        "cadastrar face",
        "registrar meu rosto",
        "salvar minha face",
        "adicionar rosto no sistema",
    ],
    "reconhecer_face": [
        "reconhecer face",
        "quem sou eu",
        "reconhecer rosto",
        "me identifica",
        "diz quem eu sou",
        "reconhece a pessoa na camera",
    ],
    "ia_generativa": [
        "me explica o que e machine learning",
        "o que e inteligencia artificial",
        "pergunta sobre ciencia",
        "me fala sobre historia",
        "explica esse conceito",
        "o que significa",
    ],
    "clima": [
        "previsao do tempo em sao paulo",
        "como esta o clima hoje",
        "qual a temperatura agora",
        "vai chover hoje",
        "como esta o tempo",
        "previsao para amanha",
    ],
    "dolar": [
        "qual o valor do dolar hoje",
        "cotacao do dolar",
        "quanto esta o cambio",
        "preco do dolar agora",
        "dolar hoje",
    ],
    "bitcoin": [
        "quanto vale um bitcoin hoje",
        "cotacao do bitcoin",
        "preco do btc",
        "valor da cripto",
        "quanto custa um bitcoin",
    ],
    "tocar_musica": [
        "tocar musica no spotify",
        "coloca uma musica pra tocar",
        "reproduzir spotify",
        "quero ouvir uma musica",
        "toca essa musica",
    ],
    "controle_midia": [
        "pausar musica",
        "proxima musica",
        "musica anterior",
        "continuar musica",
        "pausar reproducao",
        "pular faixa",
        "voltar musica",
    ],
    "pesquisar": [
        "pesquisar no google",
        "busca no google pra mim",
        "pesquisa sobre",
        "procura no google",
        "buscar informacao",
    ],
    # Extras item 10 — cross-platform (Windows e Mac)
    "volume": [
        "aumenta o volume",
        "aumente o volume",
        "diminui o volume",
        "diminua o volume",
        "volume no maximo",
        "deixa mais alto",
        "abaixa o som",
        "muta o volume",
        "mutar o volume",
        "volume mutar",
        "coloca no mudo",
        "tira do mudo",
    ],
    "screenshot": [
        "tira um print da tela",
        "captura de tela",
        "faz um screenshot",
        "tira print",
        "salva a tela",
        "print screen",
    ],
    "youtube": [
        "abre o youtube e toca um video sobre",
        "toca um video no youtube sobre",
        "abre youtube e roda um video",
        "pesquisa no youtube",
        "mostra um video sobre",
    ],
    "portal_faculdade": [
        "abre o portal da faculdade",
        "abre o portal do aluno",
        "portal fiap",
        "acessa o portal da faculdade",
        "abre o site da faculdade",
    ],
    # ── AccessFlow: sensor de luminosidade (LDR) ──
    "status_luz": [
        "como esta a iluminacao",
        "a passagem esta iluminada",
        "como esta a luz do corredor",
        "nivel de luz agora",
        "ta escuro aqui",
        "status do sensor de luz",
        "le o sensor de luz",
        "a luz esta boa",
    ],
    "calibrar_luz": [
        "calibrar luz",
        "calibrar o sensor de luz",
        "calibra a iluminacao",
        "essa e a luz normal",
        "ajustar sensor de luminosidade",
    ],
    "relatorio_luz": [
        "relatorio de iluminacao",
        "relatorio do sensor de luz",
        "resumo das ocorrencias de luz",
        "quantas vezes ficou escuro",
        "historico de iluminacao",
        "ocorrencias de pouca luz",
    ],
    "simular_luz": [
        "simular escuro",
        "simular ambiente claro",
        "simular penumbra",
        "simular falha no sensor",
        "simular pouca luz",
    ],
    "saudacao": [
        "ola tudo bem",
        "oi como vai",
        "ola chico",
        "eae tudo certo",
    ],
    "encerrar": [
        "tchau encerrar",
        "sair do sistema",
        "encerrar assistente",
        "ate logo tchau",
        "fecha o programa",
        "sair",
    ],
}


def _normalizar(texto: str) -> str:
    """Remove acentos e deixa minusculo para comparar melhor."""
    texto = texto.lower().strip()
    # Remove acentos: sao -> sao, previsao -> previsao (evita miss por STT)
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    texto = re.sub(r"\s+", " ", texto)
    return texto


class Roteador:
    """
    Classifica a instrucao do usuario em um dos intents via similaridade de embeddings.

    Por padrao usa TF-IDF (offline). Para usar embeddings reais do Gemini,
    descomente o bloco em _vetorizar_gemini e passe usar_gemini=True.
    """

    def __init__(self, usar_gemini: bool = False) -> None:
        self.usar_gemini = usar_gemini
        self._intents: list[str] = list(INTENTS_EXEMPLOS.keys())
        # Achata: lista de frases e lista paralela de labels
        self._frases: list[str] = []
        self._labels: list[str] = []
        for intent, exemplos in INTENTS_EXEMPLOS.items():
            for frase in exemplos:
                self._frases.append(_normalizar(frase))
                self._labels.append(intent)

        # Vetorizador TF-IDF — treina com as frases exemplo
        self._vetorizador = None
        self._matriz_exemplos = None  # shape: (n_frases, n_features)
        self._inicializar_tfidf()

        # Opcional: cache de centroids por intent (media dos vetores do intent)
        self._centroids: dict[str, np.ndarray] = {}
        self._calcular_centroids()

        # Tentativa de embeddings Gemini (so se pediu e tem chave)
        self._client_gemini = None
        if usar_gemini:
            self._inicializar_gemini()

        logger.info("Roteador pronto: %d intents, %d frases exemplo, modo=%s", len(self._intents), len(self._frases), "gemini" if self._client_gemini else "tfidf")

    # TF-IDF offline

    def _inicializar_tfidf(self) -> None:
        """Cria o vetorizador TF-IDF e vetoriza todas as frases exemplo."""
        from sklearn.feature_extraction.text import TfidfVectorizer

        # ngram_range (1,2) pega bigramas: "que horas" vira feature propria
        self._vetorizador = TfidfVectorizer(ngram_range=(1, 2), lowercase=False, token_pattern=r"(?u)\b\w+\b")
        self._matriz_exemplos = self._vetorizador.fit_transform(self._frases).toarray()
        # Normaliza linhas para cosseno virar dot-product
        normas = np.linalg.norm(self._matriz_exemplos, axis=1, keepdims=True)
        normas[normas == 0] = 1
        self._matriz_exemplos = self._matriz_exemplos / normas

    def _calcular_centroids(self) -> None:
        """Media dos vetores de cada intent — classifica pelo centroide mais proximo."""
        for intent in self._intents:
            indices = [i for i, lb in enumerate(self._labels) if lb == intent]
            vetores = self._matriz_exemplos[indices]
            centroide = vetores.mean(axis=0)
            norma = np.linalg.norm(centroide)
            if norma > 0:
                centroide = centroide / norma
            self._centroids[intent] = centroide

    # Gemini embeddings (opcional)

    def _inicializar_gemini(self) -> None:
        """Tenta configurar cliente Gemini para embeddings. Falha silenciosa -> cai no TF-IDF."""
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            logger.warning("GEMINI_API_KEY nao configurada, embeddings Gemini desativados.")
            return
        try:
            from google import genai as google_genai

            self._client_gemini = google_genai.Client(api_key=api_key)
            logger.info("Gemini embeddings ativado (text-embedding-004).")
        except Exception as exc:
            logger.warning("Falha ao ativar Gemini embeddings: %s", exc)
            self._client_gemini = None

    def _vetorizar_gemini(self, texto: str) -> np.ndarray | None:
        """
        Vetoriza com Gemini text-embedding-004.
        DESCOMENTAR PARA USAR EMBEDDINGS REAIS — basta trocar _vetorizar para chamar esta.
        """
        if self._client_gemini is None:
            return None
        try:
            resp = self._client_gemini.models.embed_content(model="text-embedding-004", contents=texto)
            # Novo SDK: resp.embeddings[0].values
            emb = resp.embeddings[0].values  # type: ignore[attr-defined]
            # Fallback para formatos antigos do SDK
            if emb is None and hasattr(resp, "embedding"):
                emb = resp.embedding.values  # type: ignore
            vec = np.array(emb, dtype=np.float64)
            norma = np.linalg.norm(vec)
            if norma > 0:
                vec = vec / norma
            return vec
        except Exception as exc:
            logger.warning("Falha no embedding Gemini para '%s': %s", texto[:30], exc)
            return None

    # Classificacao

    def _vetorizar(self, texto: str) -> np.ndarray:
        """
        Vetoriza a instrucao do usuario.

        Hoje usa TF-IDF. Para usar Gemini, descomente o bloco abaixo e retorne
        o vetor do Gemini quando disponivel.
        """
        # Para ativar embeddings reais do Gemini, descomente:
        # if self._client_gemini is not None:
        #     vec = self._vetorizar_gemini(texto)
        #     if vec is not None:
        #         return vec

        # TF-IDF: transforma a frase com o mesmo vetorizador treinado nos exemplos
        if self._vetorizador is None or self._matriz_exemplos is None:
            return np.zeros(1)
        mat = self._vetorizador.transform([texto]).toarray()[0]
        norma = np.linalg.norm(mat)
        if norma > 0:
            mat = mat / norma
        return mat

    def rotear(self, instrucao: str) -> tuple[str | None, float, dict[str, float]]:
        """
        Classifica a instrucao em um intent.

        Args:
            instrucao: texto ja sem o nome da assistente (ex: "que horas sao").

        Returns:
            (intent, score, todos_scores)
            - intent: nome do intent vencedor ou None se abaixo do limiar
            - score: similaridade cosseno do vencedor (0 a 1)
            - todos_scores: dict intent -> score para debug
        """
        texto = _normalizar(instrucao)
        if not texto:
            return None, 0.0, {}

        vec = self._vetorizar(texto)

        # Se o vetor e todo zero (palavras desconhecidas), nao classifica
        if np.linalg.norm(vec) == 0:
            return None, 0.0, {}

        # Compara com o centroide de cada intent (media dos exemplos do intent)
        scores: dict[str, float] = {}
        for intent, centroide in self._centroids.items():
            # Cosseno = dot-product (ambos ja normalizados)
            # Se usar Gemini embeddings, vetores tem dimensao diferente — precisaria
            # reindexar os exemplos com Gemini tambem. Por isso Gemini fica comentado.
            if centroide.shape == vec.shape:
                scores[intent] = float(np.dot(vec, centroide))
            else:
                scores[intent] = 0.0

        if not scores:
            return None, 0.0, {}

        vencedor = max(scores, key=scores.get)  # type: ignore[arg-type]
        score = scores[vencedor]

        if score < LIMIAR_SIMILARIDADE:
            logger.debug("Roteador: '%s' -> nenhum intent (melhor=%s %.2f < %.2f)", instrucao[:40], vencedor, score, LIMIAR_SIMILARIDADE)
            return None, score, scores

        logger.info("Roteador: '%s' -> %s (%.2f)", instrucao[:40], vencedor, score)
        return vencedor, score, scores

    def explicar(self, instrucao: str) -> str:
        """Texto legivel para debug / apresentacao."""
        intent, score, scores = self.rotear(instrucao)
        if intent is None:
            return f"'{instrucao}' -> sem intent (melhor={max(scores.values()) if scores else 0:.2f} < {LIMIAR_SIMILARIDADE}) -> vai pra IA"
        ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top = ", ".join(f"{k}={v:.2f}" for k, v in ranking)
        return f"'{instrucao}' -> {intent} ({score:.2f}) | top3: {top}"


if __name__ == "__main__":
    # Teste rapido sem precisar da assistente:
    #   .venv\Scripts\python.exe roteador.py
    r = Roteador()
    testes = [
        "que horas sao agora",
        "me diz o horario atual",
        "cadastrar evento na agenda",
        "marca um compromisso pra mim",
        "quanto e dez vezes cinco",
        "me diz quanto da essa conta",
        "previsao do tempo",
        "qual o valor do dolar",
        "tocar musica no spotify",
        "pausar a musica",
        "pesquisar no google",
        "quem sou eu",
        "tchau sair",
        "o que e buraco negro",  # deve cair na IA (ia_generativa)
        "explica fotossintese",  # deve cair na IA
    ]
    for t in testes:
        print(r.explicar(t))
