"""
Extras item 10 — comandos adicionais cross-platform (Windows e Mac).

Todos os metodos detectam o SO no inicio (sys.platform) e tentam a
estrategia nativa do Mac primeiro, com fallback para Windows, ou
vice-versa. Se a lib opcional nao estiver instalada, avisa e sugere
o pip install, mas nao quebra a assistente.

- screenshot: usa mss (leve) -> pyautogui -> PIL
- volume: usa pycaw (Windows) e osascript (Mac)
- youtube/portal: webbrowser (cross-platform nativo)
"""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

PORTAL_FIAP_URL = "https://on.fiap.com.br/"


def _plataforma() -> str:
    """Retorna 'windows', 'mac' ou 'linux' para log e branching."""
    # platform.system() = 'Windows' | 'Darwin' | 'Linux'
    # sys.platform = 'win32' | 'darwin' | 'linux'
    sistema = platform.system().lower()
    if sistema == "windows" or sys.platform == "win32":
        return "windows"
    if sistema == "darwin" or sys.platform == "darwin":
        return "mac"
    return "linux"


class Extras:
    """Handlers dos comandos extras do item 10, todos cross-platform."""

    def __init__(self) -> None:
        self.plataforma = _plataforma()
        logger.info("Extras inicializado na plataforma: %s", self.plataforma)

    # Screenshot

    def screenshot(self) -> str:
        """
        Tira um print da tela e salva em data/screenshots/.

        Tenta: mss (mais leve) -> pyautogui -> PIL ImageGrab.
        Nome do arquivo inclui timestamp.
        """
        destino_dir = Path("data") / "screenshots"
        destino_dir.mkdir(parents=True, exist_ok=True)
        nome = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        destino = destino_dir / nome

        # Tentativa 1: mss (leve, nao precisa de tkinter)
        try:
            import mss  # type: ignore
            import mss.tools  # type: ignore

            with mss.mss() as sct:
                monitor = sct.monitors[1]  # tela principal
                img = sct.grab(monitor)
                mss.tools.to_png(img.rgb, img.size, output=str(destino))
            logger.info("Screenshot salvo via mss: %s", destino)
            return f"Print salvo em {destino}."
        except ImportError:
            logger.debug("mss nao instalado, tentando pyautogui")
        except Exception as exc:
            logger.warning("mss falhou: %s, tentando pyautogui", exc)

        # Tentativa 2: pyautogui
        try:
            import pyautogui  # type: ignore

            pyautogui.screenshot(str(destino))
            logger.info("Screenshot salvo via pyautogui: %s", destino)
            return f"Print salvo em {destino}."
        except ImportError:
            logger.debug("pyautogui nao instalado, tentando PIL")
        except Exception as exc:
            logger.warning("pyautogui falhou: %s, tentando PIL", exc)

        # Tentativa 3: PIL ImageGrab (Windows/Mac)
        try:
            from PIL import ImageGrab  # type: ignore

            img = ImageGrab.grab()
            img.save(str(destino))
            logger.info("Screenshot salvo via PIL: %s", destino)
            return f"Print salvo em {destino}."
        except ImportError:
            return "Para tirar print, instale: pip install mss  (ou pip install pyautogui pillow)"
        except Exception as exc:
            logger.error("Screenshot falhou em todas as tentativas: %s", exc)
            return f"Nao consegui tirar o print: {exc}"

    # Volume (Windows pycaw, Mac osascript)

    def volume(self, instrucao: str) -> str:
        """
        Controla o volume do sistema.

        Entende: aumentar/aumenta/aumente, diminuir/diminui/diminua,
                 mutar/muta/mudo/silenciar, desmutar/tira do mudo.
        Logica cross-platform: detecta Mac vs Windows no inicio, tenta o nativo
        e faz retry no alternativo se falhar.
        """
        texto = instrucao.lower()

        # Classifica a acao desejada a partir da frase (inclui conjugações
        # faladas: "muta", "diminua", "aumente"...). Sem match, NÃO assume
        # aumentar — era isso que fazia "muta o volume" virar "Volume aumentado".
        if any(p in texto for p in ("mutar", "muta", "mute", "mudo", "silenciar", "silencia", "silencie")) and "tira" not in texto and "desmut" not in texto:
            acao = "mute"
        elif any(p in texto for p in ("desmut", "tira do mudo", "volta o som")):
            acao = "unmute"
        elif any(p in texto for p in ("aumenta", "aumentar", "aumente", "mais alto", "maximo", "máximo")):
            acao = "up"
        elif any(p in texto for p in ("diminui", "diminuir", "diminua", "diminue", "abaixa", "abaixar", "abaixe", "menos", "mais baixo")):
            acao = "down"
        else:
            return "Quer aumentar, diminuir ou mutar o volume?"

        # Tenta Mac primeiro se estiver no Mac, senao Windows
        if self.plataforma == "mac":
            ok = self._volume_mac(acao)
            if not ok:
                ok = self._volume_windows(acao)
        else:
            ok = self._volume_windows(acao)
            if not ok:
                ok = self._volume_mac(acao)

        if ok:
            nomes = {"up": "Volume aumentado.", "down": "Volume diminuido.", "mute": "Som no mudo.", "unmute": "Som restaurado."}
            return nomes.get(acao, "Volume ajustado.")

        # Nenhum metodo funcionou — informa como fazer manual
        if self.plataforma == "windows":
            return "Nao consegui controlar o volume. No Windows instale pycaw: pip install pycaw comtypes"
        return "Nao consegui controlar o volume no Mac. Verifique a permissao de automacao."

    def _volume_mac(self, acao: str) -> bool:
        """Controla volume no Mac via osascript. Retorna True se conseguiu."""
        # osascript funciona mesmo quando chamado do Windows? Nao, mas tentamos
        # e falhamos silenciosamente para o retry fazer o Windows.
        try:
            import shutil

            if not shutil.which("osascript"):
                return False
            if acao == "mute":
                cmd = 'set volume output muted true'
            elif acao == "unmute":
                cmd = 'set volume output muted false'
            elif acao == "up":
                cmd = 'set volume output volume ((output volume of (get volume settings)) + 10)'
            else:
                cmd = 'set volume output volume ((output volume of (get volume settings)) - 10)'
            res = subprocess.run(["osascript", "-e", cmd], capture_output=True, timeout=5)
            return res.returncode == 0
        except Exception as exc:
            logger.debug("Volume Mac falhou: %s", exc)
            return False

    def _volume_windows(self, acao: str) -> bool:
        """Controla volume no Windows via pycaw. Usa AudioDevice.EndpointVolume (API nova)."""
        try:
            from pycaw.pycaw import AudioUtilities  # type: ignore

            device = AudioUtilities.GetSpeakers()
            # pycaw novo: AudioDevice com .EndpointVolume; antigo: device.Activate
            volume = getattr(device, "EndpointVolume", None)
            if volume is None:
                from ctypes import POINTER, cast

                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume  # type: ignore

                iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)  # type: ignore[attr-defined]
                volume = cast(iface, POINTER(IAudioEndpointVolume))

            if acao == "mute":
                volume.SetMute(1, None)
            elif acao == "unmute":
                volume.SetMute(0, None)
            elif acao == "up":
                atual = volume.GetMasterVolumeLevelScalar()
                volume.SetMasterVolumeLevelScalar(min(1.0, atual + 0.15), None)
            else:
                atual = volume.GetMasterVolumeLevelScalar()
                volume.SetMasterVolumeLevelScalar(max(0.0, atual - 0.15), None)
            return True
        except ImportError:
            logger.debug("pycaw nao instalado")
            return False
        except Exception as exc:
            logger.warning("Volume Windows falhou: %s", exc)
            return False

    # YouTube

    def youtube(self, instrucao: str) -> str:
        """
        Abre o YouTube pesquisando o termo da frase.

        Extrai o termo removendo gatilhos como "abre o youtube", "toca um video sobre".
        """
        # Remove gatilhos conhecidos para sobrar so o termo de busca
        termo = instrucao.lower()
        for gatilho in ("abre o youtube e toca um video sobre", "abre o youtube e rode um video sobre", "toca um video no youtube sobre", "abre o youtube", "abre youtube", "no youtube", "youtube", "toca um video sobre", "mostra um video sobre", "pesquisa no youtube", "sobre"):
            termo = termo.replace(gatilho, " ")
        termo = " ".join(termo.split()).strip()
        if not termo:
            webbrowser.open("https://www.youtube.com/")
            return "Abri o YouTube."
        url = f"https://www.youtube.com/results?search_query={quote_plus(termo)}"
        webbrowser.open(url)
        logger.info("YouTube aberto para: %s", termo)
        return f"Abri o YouTube pesquisando '{termo}'."

    # Portal da faculdade

    def portal_faculdade(self) -> str:
        """Abre o portal da FIAP no navegador."""
        webbrowser.open(PORTAL_FIAP_URL)
        logger.info("Portal da faculdade aberto: %s", PORTAL_FIAP_URL)
        return "Abri o portal da faculdade."


if __name__ == "__main__":
    # Teste rapido:
    #   .venv\Scripts\python.exe extras.py
    e = Extras()
    print("Plataforma:", e.plataforma)
    print(e.youtube("abre o youtube e toca um video sobre python para iniciantes"))
    print(e.portal_faculdade())
