from __future__ import annotations

import arcade
import arcade.gui

from .arena_select import ArenaSelectView
from .base import BaseUI
from .lobby import LobbyView
from .rules_help import RulesHelpView
from .settings_view import SettingsView


class MainMenuView(BaseUI):
    def __init__(self) -> None:
        super().__init__()
        self.setup()

    def setup(self) -> None:
        title = arcade.gui.UILabel(text="ТАНКОВАЯ АРЕНА", font_size=42, width=500, align="center")
        self.v_box.add(title)
        self._add_button(
            "Играть локально (2 игрока)",
            lambda _: self.window.show_view(ArenaSelectView(mode="local", title="Выбор арены: локальная дуэль")),
        )
        self._add_button(
            "Играть по сети (лобби)",
            lambda _: self.window.show_view(LobbyView()),
        )
        self._add_button("Редактор уровней", lambda _: self._open_level_editor())
        self._add_button("Правила и справка", lambda _: self.window.show_view(RulesHelpView()))
        self._add_button("Настройки", lambda _: self.window.show_view(SettingsView()))
        self._add_button("Выход", lambda _: arcade.exit())
        self.mount_centered()

    def _open_level_editor(self) -> None:
        from game.app import LevelEditorView

        self.window.show_view(LevelEditorView())

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=360)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_MIDNIGHT_BLUE)
        self.ui.draw()
