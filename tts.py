"""
Síntese de voz do Chico.

Usa vozes neurais (edge-tts / Microsoft) quando há internet.
Se falhar, cai no pyttsx3 (voz do sistema, offline).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile

import pyttsx3

logger = logging.getLogger(__name__)

# Voz masculina em pt-BR (Chico). Alternativa: pt-BR-DonatoNeural
VOZ_NEURAL = "pt-BR-AntonioNeural"


class TTS:
    """Fala o texto: neural primeiro, pyttsx3 como fallback."""

    def __init__(self) -> None:
        self._engine = self._inicializar_pyttsx3()

    def _inicializar_pyttsx3(self) -> pyttsx3.Engine | None:
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            voz_pt = next(
                (
                    v
                    for v in voices
                    if "pt-br" in v.id.lower()
                    or "portuguese (brazil)" in v.name.lower()
                ),
                None,
            )
            if voz_pt:
                engine.setProperty("voice", voz_pt.id)
            elif len(voices) > 1:
                engine.setProperty("voice", voices[1].id)
            engine.setProperty("rate", 170)
            engine.setProperty("volume", 1.0)
            return engine
        except Exception as exc:
            logger.warning("Fallback pyttsx3 indisponível: %s", exc)
            return None

    def falar(self, texto: str) -> None:
        if not texto.strip():
            return
        if self._falar_neural(texto):
            return
        self._falar_sistema(texto)

    def _falar_neural(self, texto: str) -> bool:
        try:
            import edge_tts  # import local: o app sobe mesmo sem o pacote
        except ImportError:
            logger.debug("edge-tts não instalado; usando voz do sistema.")
            return False

        fd, caminho = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        try:
            asyncio.run(self._gerar_mp3(edge_tts, texto, caminho))
            self._reproduzir(caminho)
            return True
        except Exception as exc:
            logger.warning("TTS neural falhou (%s); usando voz do sistema.", exc)
            return False
        finally:
            try:
                os.remove(caminho)
            except OSError:
                pass

    @staticmethod
    async def _gerar_mp3(edge_tts, texto: str, caminho: str) -> None:
        communicate = edge_tts.Communicate(texto, VOZ_NEURAL)
        await communicate.save(caminho)

    @staticmethod
    def _reproduzir(caminho: str) -> None:
        if sys.platform == "win32":
            try:
                import pygame  # type: ignore

                pygame.mixer.init()
                pygame.mixer.music.load(caminho)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(100)
                pygame.mixer.quit()
                return
            except ImportError:
                pass
            except Exception:
                try:
                    import pygame as _pg2

                    _pg2.mixer.quit()
                except Exception:
                    pass
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", caminho],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                )
                return
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
            raise FileNotFoundError("Nenhum player de audio encontrado (instale pygame: pip install pygame)")
        if sys.platform == "darwin":
            subprocess.run(
                ["afplay", caminho],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        for cmd in (["mpg123", "-q", caminho], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", caminho], ["aplay", caminho]):
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                return
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        raise FileNotFoundError("Nenhum player de audio encontrado")

    def _falar_sistema(self, texto: str) -> None:
        if not self._engine:
            return
        try:
            self._engine.say(texto)
            self._engine.runAndWait()
        except Exception as exc:
            logger.warning("Erro ao falar: %s", exc)
