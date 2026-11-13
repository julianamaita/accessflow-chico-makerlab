"""
Módulo de mídia.
Toca músicas de verdade no Spotify (app desktop) e pesquisa no Google.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from typing import Any
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"


class Midia:
    """Gerencia reprodução no Spotify e pesquisas web."""

    def __init__(self) -> None:
        self._client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        self._client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        self._token: str = ""
        self._token_expira_em: float = 0.0

    # ------------------------------------------------------------------ #
    #  Spotify                                                             #
    # ------------------------------------------------------------------ #

    def tocar_spotify(self, musica: str) -> str:
        """
        Busca a faixa e inicia a reprodução no app do Spotify.

        Args:
            musica: nome da música, artista ou ambos.

        Returns:
            Mensagem para a assistente falar.
        """
        if not musica:
            return "Não entendi qual música tocar."

        faixa = self._buscar_faixa(musica)
        if faixa is None:
            if not self._client_id or not self._client_secret:
                self._abrir_busca_web(musica)
                return (
                    "Para tocar de verdade, configure SPOTIFY_CLIENT_ID e "
                    "SPOTIFY_CLIENT_SECRET no arquivo .env. Abri a busca no navegador."
                )
            self._abrir_busca_web(musica)
            return f"Não encontrei '{musica}' no Spotify. Abri a busca no navegador."

        uri = faixa["uri"]
        if self._reproduzir_no_app(uri):
            return f"Tocando {faixa['nome']}, de {faixa['artista']}."

        webbrowser.open(faixa["url"])
        return f"Encontrei {faixa['nome']}, de {faixa['artista']}."

    def pausar(self) -> str:
        """Pausa a reprodução no app do Spotify."""
        if self._osascript('tell application "Spotify" to pause'):
            return "Música pausada."
        return "Não consegui pausar. Abra o Spotify no computador e tente de novo."

    def continuar(self) -> str:
        """Retoma a reprodução no app do Spotify."""
        if self._osascript('tell application "Spotify" to play'):
            return "Continuando a música."
        return "Não consegui continuar. Abra o Spotify no computador e tente de novo."

    def proxima(self) -> str:
        """Pula para a próxima faixa."""
        if self._osascript('tell application "Spotify" to next track'):
            return "Próxima música."
        return "Não consegui pular a faixa. Abra o Spotify no computador."

    def anterior(self) -> str:
        """Volta para a faixa anterior."""
        if self._osascript('tell application "Spotify" to previous track'):
            return "Música anterior."
        return "Não consegui voltar a faixa. Abra o Spotify no computador."

    # ------------------------------------------------------------------ #
    #  Google                                                              #
    # ------------------------------------------------------------------ #

    def pesquisar_google(self, termo: str) -> None:
        """
        Realiza uma pesquisa no Google.

        Args:
            termo: texto a pesquisar.
        """
        if not termo:
            logger.warning("Termo de pesquisa vazio.")
            return
        url = f"https://www.google.com/search?q={quote_plus(termo)}"
        webbrowser.open(url)
        logger.info("Google aberto para: %s", termo)

    # ------------------------------------------------------------------ #
    #  Internos                                                            #
    # ------------------------------------------------------------------ #

    def _token_acesso(self) -> str | None:
        """Obtém (e cacheia) um token Client Credentials da API do Spotify."""
        if self._token and time.time() < self._token_expira_em:
            return self._token
        if not self._client_id or not self._client_secret:
            return None

        credenciais = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            resposta = requests.post(
                SPOTIFY_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credenciais}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
                timeout=10,
            )
            resposta.raise_for_status()
            dados: dict[str, Any] = resposta.json()
            self._token = str(dados["access_token"])
            self._token_expira_em = time.time() + int(dados.get("expires_in", 3600)) - 60
            logger.info("Token Spotify obtido.")
            return self._token
        except requests.RequestException as exc:
            logger.error("Erro ao autenticar no Spotify: %s", exc)
            return None

    def _buscar_faixa(self, musica: str) -> dict[str, str] | None:
        """Busca a primeira faixa correspondente na API do Spotify."""
        token = self._token_acesso()
        if not token:
            return None
        try:
            resposta = requests.get(
                SPOTIFY_SEARCH_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"q": musica, "type": "track", "limit": 1, "market": "BR"},
                timeout=10,
            )
            resposta.raise_for_status()
            itens = resposta.json().get("tracks", {}).get("items", [])
            if not itens:
                return None
            item = itens[0]
            artistas = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
            return {
                "nome": str(item.get("name", musica)),
                "artista": artistas or "artista desconhecido",
                "uri": str(item["uri"]),
                "url": str(item.get("external_urls", {}).get("spotify", "")),
            }
        except requests.RequestException as exc:
            logger.error("Erro ao buscar faixa no Spotify: %s", exc)
            return None

    def _reproduzir_no_app(self, uri: str) -> bool:
        """Manda o app desktop do Spotify tocar a URI."""
        if sys.platform == "darwin":
            if shutil.which("osascript") and self._osascript(
                f'tell application "Spotify" to play track "{uri}"'
            ):
                return True
            return self._abrir_uri_sistema(uri)

        if sys.platform == "win32":
            try:
                os.startfile(uri)  # type: ignore[attr-defined]
                return True
            except OSError as exc:
                logger.warning("Falha ao abrir URI do Spotify no Windows: %s", exc)
                return False

        return self._abrir_uri_sistema(uri)

    def _osascript(self, script: str) -> bool:
        """Executa AppleScript. Só funciona no macOS com o Spotify instalado."""
        if sys.platform != "darwin" or not shutil.which("osascript"):
            return False
        try:
            resultado = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if resultado.returncode != 0:
                logger.warning("AppleScript Spotify falhou: %s", resultado.stderr.strip())
                return False
            return True
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Erro ao controlar o Spotify: %s", exc)
            return False

    def _abrir_uri_sistema(self, uri: str) -> bool:
        """Abre a URI spotify:track:... no handler do sistema."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", uri], check=True, timeout=10)
                return True
            if shutil.which("xdg-open"):
                subprocess.run(["xdg-open", uri], check=True, timeout=10)
                return True
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.warning("Não foi possível abrir a URI do Spotify: %s", exc)
        return False

    def _abrir_busca_web(self, musica: str) -> None:
        url = f"https://open.spotify.com/search/{quote_plus(musica)}"
        webbrowser.open(url)
        logger.info("Spotify Web aberto para: %s", musica)
