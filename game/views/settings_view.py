from __future__ import annotations

import arcade
import arcade.gui

from .base import BaseUI


class SettingsView(BaseUI):
    def __init__(self) -> None:
        super().__init__()
        self.music = False
        self.sfx = True
        self.setup()

    def setup(self) -> None:
        from .main_menu import MainMenuView

        self.v_box.add(arcade.gui.UILabel(text="Настройки игры", font_size=28))
        music_btn = arcade.gui.UIFlatButton(text="Музыка: OFF", width=260)
        sfx_btn = arcade.gui.UIFlatButton(text="SFX: ON", width=260)
        back_btn = arcade.gui.UIFlatButton(text="Назад", width=260)

        def toggle_music(_):
            self.music = not self.music
            music_btn.text = f"Музыка: {'ON' if self.music else 'OFF'}"

        def toggle_sfx(_):
            self.sfx = not self.sfx
            sfx_btn.text = f"SFX: {'ON' if self.sfx else 'OFF'}"

        music_btn.on_click = toggle_music
        sfx_btn.on_click = toggle_sfx
        back_btn.on_click = lambda _: self.window.show_view(MainMenuView())
        self.v_box.add(music_btn)
        self.v_box.add(sfx_btn)
        self.v_box.add(back_btn)
        self.mount_centered()

    def on_draw(self) -> None:
        self.clear(color=arcade.color.PRUSSIAN_BLUE)
        self.ui.draw()
