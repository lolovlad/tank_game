from __future__ import annotations

import json
import socket
import threading
from collections import deque
from dataclasses import dataclass


@dataclass
class LobbyConfig:
    host: str = "127.0.0.1"
    port: int = 57991
    player_name: str = "player"
    room_name: str = "room"


class NetworkPeer:
    def __init__(self) -> None:
        self.socket: socket.socket | None = None
        self.connection: socket.socket | None = None
        self.listener: threading.Thread | None = None
        self.running = False
        self._inbox: deque[dict] = deque(maxlen=512)

    @property
    def connected(self) -> bool:
        return self.connection is not None

    def host(self, config: LobbyConfig) -> None:
        self.close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((config.host, config.port))
        self.socket.listen(1)
        self.running = True
        self.listener = threading.Thread(target=self._accept_loop, daemon=True)
        self.listener.start()

    def _accept_loop(self) -> None:
        assert self.socket is not None
        conn, _ = self.socket.accept()
        self.connection = conn
        self._read_loop(conn)

    def join(self, config: LobbyConfig) -> None:
        self.close()
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.connect((config.host, config.port))
        self.running = True
        self.listener = threading.Thread(target=self._read_loop, args=(self.connection,), daemon=True)
        self.listener.start()

    def _read_loop(self, sock: socket.socket) -> None:
        buff = b""
        while self.running:
            try:
                data = sock.recv(2048)
            except OSError:
                break
            if not data:
                break
            buff += data
            while b"\n" in buff:
                raw, buff = buff.split(b"\n", 1)
                if not raw:
                    continue
                try:
                    self._inbox.append(json.loads(raw.decode("utf-8")))
                except json.JSONDecodeError:
                    continue
        self.running = False

    def send(self, payload: dict) -> None:
        encoded = (json.dumps(payload) + "\n").encode("utf-8")
        target = self.connection
        if target is None:
            return
        try:
            target.sendall(encoded)
        except OSError:
            self.running = False

    def read(self) -> dict | None:
        if not self._inbox:
            return None
        return self._inbox.popleft()

    def push_front(self, msg: dict) -> None:
        """Вернуть сообщение в начало очереди (если прочитали раньше времени)."""
        self._inbox.appendleft(msg)

    def close(self) -> None:
        self.running = False
        for sock in (self.connection, self.socket):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass
        self.connection = None
        self.socket = None
        self._inbox.clear()
