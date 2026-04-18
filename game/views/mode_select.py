from __future__ import annotations

import arcade
import arcade.gui

from .base import BaseUI


class ModeSelectView(BaseUI):
    def __init__(self) -> None:
        super().__init__()
        self.setup()

    def setup(self) -> None:
        from .main_menu import MainMenuView

        self.v_box.add(arcade.gui.UILabel(text="Режимы локальной игры", font_size=28))
        self._add_button("Человек vs Человек", lambda _: self._open_local())
        self._add_button("Назад", lambda _: self.window.show_view(MainMenuView()))
        self.mount_centered()

    def _open_local(self) -> None:
        from game.app import GameView

        self.window.show_view(GameView(mode="local"))

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=300)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_SLATE_BLUE)
        self.ui.draw()
