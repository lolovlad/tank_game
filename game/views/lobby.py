from __future__ import annotations

import uuid

import arcade
import arcade.gui

from ..config import SCREEN_HEIGHT, SCREEN_WIDTH, SERVER_PORT
from ..lobby_handshake import NET_MSG_LOBBY_HANDSHAKE, guess_lan_ipv4, wait_for_lobby_handshake
from ..network import LobbyConfig, NetworkPeer
from .base import BaseUI


class LobbyView(BaseUI):
    """Хаб онлайна: арену выбирает только создатель лобби; гость подключается без выбора карты."""

    def __init__(self) -> None:
        super().__init__()
        self.setup()

    def setup(self) -> None:
        from .main_menu import MainMenuView

        self.v_box.add(arcade.gui.UILabel(text="Сетевое лобби", font_size=28))
        self.v_box.add(
            arcade.gui.UILabel(
                text="Создатель лобби выбирает арену. Подключающийся игрок получит ту же карту от хоста.",
                font_size=13,
                width=560,
                align="center",
            )
        )
        self._add_button("Создать лобби", lambda _: self._open_host_arena_select())
        self._add_button("Подключиться к лобби", lambda _: self.window.show_view(ClientConnectView()))
        self._add_button("Назад", lambda _: self.window.show_view(MainMenuView()))
        self.mount_centered()

    def _open_host_arena_select(self) -> None:
        from .arena_select import ArenaSelectView

        self.window.show_view(ArenaSelectView(mode="online_host", title="Выбор арены для лобби"))

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=320)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.BLACK_OLIVE)
        self.ui.draw()


class HostWaitingView(BaseUI):
    """Хост: слушает порт, показывает как подключиться; игра начинается после входа клиента."""

    def __init__(self, level_name: str) -> None:
        super().__init__()
        self.level_name = level_name
        self.peer = NetworkPeer()
        self.bind_error: str | None = None
        self._game_started = False
        self.lan_ip = guess_lan_ipv4()
        self.setup()
        self._try_bind()

    def on_show_view(self) -> None:
        super().on_show_view()
        self.window.set_size(SCREEN_WIDTH, SCREEN_HEIGHT)

    def setup(self) -> None:
        self.v_box.add(arcade.gui.UILabel(text="Лобби: ожидание игрока", font_size=26, width=640, align="center"))
        self.v_box.add(
            arcade.gui.UILabel(
                text=f"Арена: {self.level_name}   ·   порт TCP: {SERVER_PORT}",
                font_size=15,
                width=640,
                align="center",
            )
        )
        self.hint_local = arcade.gui.UILabel(
            text="На этом компьютере второй процесс может подключиться к адресу 127.0.0.1",
            font_size=13,
            width=640,
            align="center",
        )
        self.v_box.add(self.hint_local)
        self.hint_lan = arcade.gui.UILabel(
            text=self._lan_hint_text(),
            font_size=13,
            width=640,
            align="center",
        )
        self.v_box.add(self.hint_lan)
        self.v_box.add(
            arcade.gui.UILabel(
                text="Второй игрок: главное меню → по сети → «Подключиться к лобби», "
                "вводит IP хоста и порт, нажимает «Подключиться».",
                font_size=12,
                width=640,
                align="center",
            )
        )
        self.status = arcade.gui.UILabel(
            text="Запуск сервера…", font_size=14, width=640, align="center", text_color=arcade.color.LIGHT_GRAY
        )
        self.v_box.add(self.status)
        self._add_button("Отмена", self._on_cancel)
        self.mount_centered()

    def _lan_hint_text(self) -> str:
        if self.lan_ip:
            return f"С другого ПК в сети укажите IP: {self.lan_ip}  и порт: {SERVER_PORT}"
        return "LAN-адрес не определён автоматически — узнайте IP этого ПК в настройках сети."

    def _try_bind(self) -> None:
        try:
            self.peer.host(LobbyConfig(host="0.0.0.0", port=SERVER_PORT))
            self.status.text = "Ожидаем подключение второго игрока…"
            self.bind_error = None
        except OSError as exc:
            self.bind_error = str(exc)
            self.status.text = f"Не удалось открыть порт {SERVER_PORT}: {exc}"

    def _on_cancel(self, _event) -> None:
        self.peer.close()
        self.window.show_view(LobbyView())

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=320)
        button.on_click = callback
        self.v_box.add(button)

    def on_update(self, delta_time: float) -> None:
        if self.bind_error or self._game_started:
            return
        if self.peer.connected:
            self._game_started = True
            session_id = str(uuid.uuid4())
            self.peer.send(
                {
                    "type": NET_MSG_LOBBY_HANDSHAKE,
                    "level_name": self.level_name,
                    "your_slot": 2,
                    "session_id": session_id,
                }
            )
            from game.app import GameView

            self.window.show_view(
                GameView(
                    mode="online_host",
                    level_name=self.level_name,
                    network_peer=self.peer,
                    network_session_id=session_id,
                    network_my_slot=1,
                )
            )

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key == arcade.key.ESCAPE:
            self._on_cancel(None)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.BLACK_OLIVE)
        self.ui.draw()


class ClientConnectView(BaseUI):
    """Клиент: ввод IP и порта, подключение; арена приходит от хоста; игра после рукопожатия."""

    def __init__(self) -> None:
        super().__init__()
        self.peer: NetworkPeer | None = None
        self.setup()

    def on_show_view(self) -> None:
        super().on_show_view()
        self.window.set_size(SCREEN_WIDTH, SCREEN_HEIGHT)

    def setup(self) -> None:
        self.v_box.add(arcade.gui.UILabel(text="Подключение к лобби", font_size=26, width=520, align="center"))
        self.v_box.add(
            arcade.gui.UILabel(
                text="Арену выбирает хост — после подключения вы получите ту же карту автоматически.",
                font_size=13,
                width=520,
                align="center",
            )
        )
        self.v_box.add(
            arcade.gui.UILabel(
                text="Введите адрес хоста и порт (как на экране ожидания у создателя лобби).",
                font_size=13,
                width=520,
                align="center",
            )
        )
        self.v_box.add(arcade.gui.UILabel(text="IP или имя хоста", font_size=12, width=400, align="left"))
        self.host_field = arcade.gui.UIInputText(width=400, height=32, text="127.0.0.1", font_size=14)
        self.v_box.add(self.host_field)
        self.v_box.add(arcade.gui.UILabel(text="Порт", font_size=12, width=400, align="left"))
        self.port_field = arcade.gui.UIInputText(width=400, height=32, text=str(SERVER_PORT), font_size=14)
        self.v_box.add(self.port_field)
        self.status = arcade.gui.UILabel(
            text="", font_size=13, width=520, align="center", text_color=arcade.color.ORANGE_PEEL
        )
        self.v_box.add(self.status)
        connect = arcade.gui.UIFlatButton(text="Подключиться", width=320)
        connect.on_click = self._on_connect
        self.v_box.add(connect)
        self._add_button("Назад", lambda _: self.window.show_view(LobbyView()))
        self.mount_centered()

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=320)
        button.on_click = callback
        self.v_box.add(button)

    def _on_connect(self, _event) -> None:
        from game.app import GameView

        if self.peer:
            self.peer.close()
            self.peer = None
        host = (self.host_field.text or "").strip()
        port_raw = (self.port_field.text or "").strip()
        if not host:
            self.status.text = "Укажите адрес хоста."
            return
        try:
            port = int(port_raw)
        except ValueError:
            self.status.text = "Порт должен быть числом."
            return
        if not (1 <= port <= 65535):
            self.status.text = "Порт должен быть от 1 до 65535."
            return
        self.status.text = "Подключение…"
        peer = NetworkPeer()
        try:
            peer.join(LobbyConfig(host=host, port=port))
        except OSError as exc:
            peer.close()
            self.status.text = f"Не удалось подключиться: {exc}"
            return
        if not peer.running:
            peer.close()
            self.status.text = "Соединение сразу разорвалось."
            return
        self.status.text = "Ожидание данных лобби от хоста…"
        handshake = wait_for_lobby_handshake(peer)
        if not handshake:
            peer.close()
            self.status.text = "Хост не прислал данные лобби (таймаут или обрыв). Попробуйте снова."
            return
        self.peer = peer
        self.window.show_view(
            GameView(
                mode="online_client",
                level_name=handshake.level_name,
                network_peer=peer,
                network_session_id=handshake.session_id,
                network_my_slot=handshake.your_slot,
            )
        )

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key == arcade.key.ESCAPE:
            if self.peer:
                self.peer.close()
            self.window.show_view(LobbyView())

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_SLATE_BLUE)
        self.ui.draw()
