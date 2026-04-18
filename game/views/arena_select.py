from __future__ import annotations

import arcade
import arcade.gui

from ..level import level_display_name, level_names
from .base import BaseUI
from .lobby import HostWaitingView, LobbyView


class ArenaSelectView(BaseUI):
    def __init__(self, mode: str, title: str) -> None:
        super().__init__()
        self.mode = mode
        self.title = title
        self.setup()

    def setup(self) -> None:
        from .main_menu import MainMenuView

        self.v_box.add(arcade.gui.UILabel(text=self.title, font_size=24))
        for arena_name in level_names():
            self._add_button(
                level_display_name(arena_name),
                lambda _, name=arena_name: self._open_mode_with_arena(name),
            )
        if self.mode == "online_host":
            self._add_button("Назад", lambda _: self.window.show_view(LobbyView()))
        else:
            self._add_button("Назад", lambda _: self.window.show_view(MainMenuView()))
        self.mount_centered()

    def _open_mode_with_arena(self, arena_name: str) -> None:
        if self.mode == "online_host":
            self.window.show_view(HostWaitingView(arena_name))
            return
        from game.app import GameView

        self.window.show_view(GameView(mode=self.mode, level_name=arena_name))

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=360)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_SLATE_BLUE)
        self.ui.draw()
