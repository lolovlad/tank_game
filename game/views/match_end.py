from __future__ import annotations

import arcade
import arcade.gui

from ..lobby_handshake import NET_MSG_REMATCH_READY, NET_MSG_REMATCH_START
from ..network import NetworkPeer
from .arena_select import ArenaSelectView
from .base import BaseUI
from .lobby import LobbyView


class MatchEndView(BaseUI):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.setup()

    def setup(self) -> None:
        from .main_menu import MainMenuView

        self.v_box.add(arcade.gui.UILabel(text=self.title, font_size=40, width=520, align="center"))
        self.v_box.add(arcade.gui.UILabel(text=self.subtitle, font_size=18, width=520, align="center"))
        self._add_button(
            "Сыграть снова",
            lambda _: self.window.show_view(ArenaSelectView(mode="local", title="Выбор арены: локальная дуэль")),
        )
        self._add_button("Главное меню", lambda _: self.window.show_view(MainMenuView()))
        self.mount_centered()

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=320)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.BLACK)
        self.ui.draw()


class OnlineMatchEndView(BaseUI):
    def __init__(
        self,
        title: str,
        subtitle: str,
        level_name: str,
        mode: str,
        peer: NetworkPeer,
        network_session_id: str | None,
        network_my_slot: int,
    ) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.level_name = level_name
        self.mode = mode
        self.peer = peer
        self.network_session_id = network_session_id
        self.network_my_slot = network_my_slot
        self._local_ready = False
        self._remote_ready = False
        self._finished = False
        self.status_label: arcade.gui.UILabel | None = None
        self.setup()

    def setup(self) -> None:
        self.v_box.add(arcade.gui.UILabel(text=self.title, font_size=40, width=620, align="center"))
        self.v_box.add(arcade.gui.UILabel(text=self.subtitle, font_size=18, width=620, align="center"))
        self.status_label = arcade.gui.UILabel(
            text="Нажмите «Сыграть снова». Матч начнётся, когда оба игрока подтвердят.",
            font_size=14,
            width=620,
            align="center",
            text_color=arcade.color.LIGHT_GRAY,
        )
        self.v_box.add(self.status_label)
        self._add_button("Сыграть снова", self._on_rematch_click)
        self._add_button("Главное меню", self._on_exit_click)
        self.mount_centered()

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=320)
        button.on_click = callback
        self.v_box.add(button)

    def _on_exit_click(self, _event) -> None:
        from .main_menu import MainMenuView

        if self.peer:
            self.peer.close()
        self.window.show_view(MainMenuView())

    def _on_rematch_click(self, _event) -> None:
        if self._finished:
            return
        if not self.peer.running:
            self._handle_disconnect()
            return
        self._local_ready = True
        if self.mode == "online_host":
            if self.status_label:
                self.status_label.text = "Хост готов. Ждём подтверждение второго игрока..."
            self._try_start_as_host()
            return
        self.peer.send(
            {
                "type": NET_MSG_REMATCH_READY,
                "session_id": self.network_session_id,
                "slot": self.network_my_slot,
            }
        )
        if self.status_label:
            self.status_label.text = "Запрос отправлен. Ждём, пока хост запустит новый матч..."

    def _session_matches(self, message: dict) -> bool:
        incoming_sid = message.get("session_id")
        return self.network_session_id is None or incoming_sid == self.network_session_id

    def _handle_disconnect(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self.peer:
            self.peer.close()
        self.window.show_view(LobbyView())

    def _start_new_match(self) -> None:
        if self._finished:
            return
        self._finished = True
        from game.app import GameView

        self.window.show_view(
            GameView(
                mode=self.mode,
                level_name=self.level_name,
                network_peer=self.peer,
                network_session_id=self.network_session_id,
                network_my_slot=self.network_my_slot,
            )
        )

    def _try_start_as_host(self) -> None:
        if self.mode != "online_host" or not self._local_ready or not self._remote_ready:
            return
        self.peer.send(
            {
                "type": NET_MSG_REMATCH_START,
                "session_id": self.network_session_id,
                "level_name": self.level_name,
            }
        )
        self._start_new_match()

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key == arcade.key.ESCAPE:
            self._on_exit_click(None)

    def on_update(self, delta_time: float) -> None:
        if self._finished:
            return
        if not self.peer.running:
            self._handle_disconnect()
            return
        while True:
            msg = self.peer.read()
            if msg is None:
                break
            msg_type = msg.get("type")
            if msg_type == NET_MSG_REMATCH_READY and self.mode == "online_host" and self._session_matches(msg):
                self._remote_ready = True
                if self.status_label:
                    self.status_label.text = (
                        "Игрок подключился к реваншу. Нажмите «Сыграть снова», если ещё не нажато."
                    )
                self._try_start_as_host()
            elif msg_type == NET_MSG_REMATCH_START and self.mode == "online_client" and self._session_matches(msg):
                self._start_new_match()

    def on_draw(self) -> None:
        self.clear(color=arcade.color.BLACK)
        self.ui.draw()
