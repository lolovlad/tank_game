"""Базовый класс UI-экранов на arcade.gui."""

from __future__ import annotations

import arcade
import arcade.gui


class BaseUI(arcade.View):
    def __init__(self) -> None:
        super().__init__()
        self.ui = arcade.gui.UIManager()
        self.v_box = arcade.gui.UIBoxLayout(space_between=10)

    def on_show_view(self) -> None:
        self.ui.enable()

    def on_hide_view(self) -> None:
        self.ui.disable()

    def mount_centered(self) -> None:
        root = arcade.gui.UIAnchorLayout()
        root.add(child=self.v_box, anchor_x="center_x", anchor_y="center_y")
        self.ui.add(root)
