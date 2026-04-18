"""Протокол лобби поверх TCP и вспомогательные сетевые утилиты."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

from .network import NetworkPeer

NET_MSG_LOBBY_HANDSHAKE = "lobby_handshake"
NET_MSG_REMATCH_READY = "rematch_ready"
NET_MSG_REMATCH_START = "rematch_start"


@dataclass(frozen=True)
class LobbyHandshakeResult:
    level_name: str
    your_slot: int
    session_id: str | None


def guess_lan_ipv4() -> str | None:
    """Адрес для подсказки второму игроку в LAN (без гарантии при экзотической сети)."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        finally:
            probe.close()
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None


def wait_for_lobby_handshake(peer: NetworkPeer, deadline_sec: float = 20.0) -> LobbyHandshakeResult | None:
    """После TCP ждём рукопожатие: арена, слот игрока (1=хост, 2=гость), session_id."""
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline and peer.running:
        msg = peer.read()
        if msg is None:
            time.sleep(0.02)
            continue
        if msg.get("type") == NET_MSG_LOBBY_HANDSHAKE:
            name = msg.get("level_name")
            if not isinstance(name, str) or not name.strip():
                return None
            raw_slot = msg.get("your_slot", 2)
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                slot = 2
            if slot not in (1, 2):
                slot = 2
            sid = msg.get("session_id")
            session_id = sid if isinstance(sid, str) and sid else None
            return LobbyHandshakeResult(level_name=name.strip(), your_slot=slot, session_id=session_id)
        peer.push_front(msg)
        return None
    return None
