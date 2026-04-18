"""Экран «Правила и справка»: секции, иконки, прокрутка с обрезкой по панели."""

from __future__ import annotations

import arcade
import arcade.gui
from arcade.types.rect import XYWH

from ..config import ROUND_COUNT, ROUND_WIN_TARGET, SCREEN_HEIGHT, SCREEN_WIDTH
from ..textures import texture_for

# Единый цвет заголовков секций (золотистый, как в дуэльном HUD)
_SECTION_TITLE_COLOR = (255, 221, 140, 255)

# Специальные ключи «иконок», не из IMAGE_MAP
_ICON_FOG = "__deco_fog__"
_ICON_LAN = "__deco_lan__"
_ICON_DISK = "__deco_disk__"


def _rules_help_sections() -> list[tuple[str | None, str, list[str]]]:
    return [
        (
            "icon",
            "Матч и победа",
            [
                f"Первый игрок, набравший {ROUND_WIN_TARGET} побед в раундах, выигрывает матч.",
                f"В матче не больше {ROUND_COUNT} раундов.",
                "Раунд выигрывает тот, кто первым лишит врага всех очков здоровья (сердечки вверху).",
            ],
        ),
        (
            "tank_player",
            "Локально: игрок 1",
            [
                "Движение — клавиши W A S D.",
                "Выстрел — Пробел (если есть патроны и перезарядка готова).",
            ],
        ),
        (
            "tank_enemy",
            "Локально: игрок 2",
            [
                "Движение — стрелки на клавиатуре.",
                "Выстрел — левый или правый Ctrl.",
            ],
        ),
        (
            "bullet",
            "Снаряды",
            [
                "Пули отскакивают от металла и ломают кирпичные стены.",
                "Попадание по танку снимает 1 HP.",
            ],
        ),
        (
            "pickup_ammo",
            "Предметы на арене",
            [
                "Патроны — больше выстрелов.",
                "Сердце — восстанавливает HP (до максимума).",
                "Ускорение — на время увеличивает скорость танка.",
                "Подбор: наехать танком на клетку с предметом.",
            ],
        ),
        (
            _ICON_FOG,
            "Туман войны",
            [
                "Видна только область вокруг твоего танка — у каждого игрока свой туман.",
                "То, что вне зоны видимости, скрыто, пока не подъедешь ближе.",
            ],
        ),
        (
            _ICON_LAN,
            "Игра по сети",
            [
                "Создатель лобби выбирает карту и ждёт второго игрока.",
                "Второй вводит IP и порт с экрана лобби хоста и подключается.",
                "Управление своим танком — как у игрока 1: WASD и Пробел.",
            ],
        ),
        (
            "wall_breakable",
            "Редактор: рисование",
            [
                "ЛКМ — поставить выбранную кисть в клетку.",
                "ПКМ — очистить клетку до пустого пола.",
                "Края поля металлом; внутри можно менять клетки свободно.",
            ],
        ),
        (
            "wall_metal",
            "Редактор: кисти (клавиши)",
            [
                "1 — кирпич (разрушаемая стена).",
                "2 — металл (непростреливаемая стена).",
                "3 — спавн первого танка (жёлтый), одна точка на карту.",
                "4 — спавн второго танка (серый), одна точка на карту.",
                "0 — ластик (пустая клетка).",
            ],
        ),
        (
            _ICON_DISK,
            "Редактор: файлы и выход",
            [
                "S — сохранить уровень в файл под текущим именем.",
                "R или кнопка «Сбросить поле» — очистить сетку редактора.",
                "ESC — выход в главное меню.",
            ],
        ),
    ]


def _draw_fog_icon(cx: float, cy: float, size: float) -> None:
    r = size * 0.42
    arcade.draw_circle_filled(cx, cy - r * 0.1, r * 1.05, (85, 92, 108, 240))
    arcade.draw_circle_filled(cx - r * 0.2, cy + r * 0.15, r * 0.55, (140, 148, 165, 200))
    arcade.draw_circle_filled(cx + r * 0.25, cy - r * 0.05, r * 0.35, (190, 198, 210, 160))


def _draw_lan_icon(cx: float, cy: float, size: float) -> None:
    w = size * 0.42
    rw = size * 0.86
    rh = size * 0.5
    arcade.draw_lbwh_rectangle_outline(cx - rw * 0.5, cy - rh * 0.5, rw, rh, arcade.color.LIGHT_STEEL_BLUE, 2)
    for i in range(4):
        y = cy - w * 0.35 + i * w * 0.22
        arcade.draw_line(cx - w, y, cx + w, y + w * 0.08 * (1 if i % 2 == 0 else -1), (120, 180, 255, 255), 2)


def _draw_disk_icon(cx: float, cy: float, size: float) -> None:
    w = size * 0.5
    h = size * 0.35
    arcade.draw_lbwh_rectangle_filled(cx - w * 0.5, cy - h * 0.2, w, h, (90, 110, 140, 255))
    arcade.draw_lbwh_rectangle_outline(cx - w * 0.5, cy - h * 0.2, w, h, arcade.color.LIGHT_GRAY, 1)
    arcade.draw_triangle_filled(
        cx - w * 0.48,
        cy + h * 0.5,
        cx + w * 0.48,
        cy + h * 0.5,
        cx,
        cy + h * 0.95,
        (140, 160, 190, 255),
    )


def _draw_section_icon(icon_key: str | None, icon_x: float, y_top: float, icon_size: float) -> None:
    cy = y_top - icon_size * 0.5 + 2
    if icon_key in (None, ""):
        return
    if icon_key == _ICON_FOG:
        _draw_fog_icon(icon_x, cy, icon_size)
        return
    if icon_key == _ICON_LAN:
        _draw_lan_icon(icon_x, cy, icon_size)
        return
    if icon_key == _ICON_DISK:
        _draw_disk_icon(icon_x, cy, icon_size)
        return
    tex = texture_for(icon_key)
    if tex:
        arcade.draw_texture_rect(tex, XYWH(icon_x, cy, icon_size, icon_size), angle=0)


class RulesHelpView(arcade.View):
    _TITLE_GAP = 8
    _SECTION_GAP = 10
    _ICON_SIZE = 28

    def __init__(self) -> None:
        super().__init__()
        self._ui = arcade.gui.UIManager()
        self._ui.enable()
        back = arcade.gui.UIFlatButton(text="Назад в меню", width=380, height=44)
        back.on_click = lambda _: self._go_back()
        root = arcade.gui.UIAnchorLayout()
        root.add(child=back, anchor_x="center_x", anchor_y="bottom", align_y=24)
        self._ui.add(root)

    def _go_back(self) -> None:
        from .main_menu import MainMenuView

        self.window.show_view(MainMenuView())

    def on_show_view(self) -> None:
        self.window.set_size(SCREEN_WIDTH, SCREEN_HEIGHT)
        self._ui.enable()

    def on_hide_view(self) -> None:
        self._ui.disable()

    def _draw_section(self, left: float, top: float, width: float, icon_key: str | None, title: str, lines: list[str]) -> float:
        icon_x = left + self._ICON_SIZE * 0.5
        _draw_section_icon(icon_key, icon_x, top, self._ICON_SIZE)
        arcade.draw_text(
            title,
            left + self._ICON_SIZE + 10,
            top,
            _SECTION_TITLE_COLOR,
            font_size=14,
            bold=True,
            anchor_x="left",
            anchor_y="top",
        )

        y = top - 20 - self._TITLE_GAP
        text_left = left + self._ICON_SIZE + 10
        text_width = width - self._ICON_SIZE - 12

        if title == "Предметы на арене":
            ix = text_left
            for pk in ("pickup_ammo", "pickup_hp", "pickup_speed"):
                pt = texture_for(pk)
                if pt:
                    arcade.draw_texture_rect(pt, XYWH(ix + 12, y - 10, 22, 22), angle=0)
                    ix += 50
            y -= 24

        for line in lines:
            block = arcade.Text(
                line,
                text_left,
                y,
                arcade.color.LIGHT_GRAY,
                font_size=12,
                width=text_width,
                multiline=True,
                anchor_x="left",
                anchor_y="top",
            )
            block.draw()
            y -= block.content_height + 4

        return y - self._SECTION_GAP

    def on_draw(self) -> None:
        self.clear(arcade.color.DARK_SLATE_GRAY)
        margin = 26
        panel_top = SCREEN_HEIGHT - 72
        panel_bottom = 96
        pw = SCREEN_WIDTH - 2 * margin
        ph = panel_top - panel_bottom

        arcade.draw_lbwh_rectangle_filled(margin, panel_bottom, pw, ph, (16, 20, 32, 255))
        arcade.draw_lbwh_rectangle_outline(margin, panel_bottom, pw, ph, arcade.color.LIGHT_STEEL_BLUE, 2)

        arcade.draw_text(
            "Правила и справка",
            SCREEN_WIDTH / 2,
            SCREEN_HEIGHT - 28,
            arcade.color.WHITE,
            font_size=24,
            bold=True,
            anchor_x="center",
            anchor_y="center",
        )
        arcade.draw_text(
            "Все правила на одной странице",
            SCREEN_WIDTH / 2,
            SCREEN_HEIGHT - 50,
            arcade.color.LIGHT_GRAY,
            font_size=12,
            anchor_x="center",
            anchor_y="center",
        )

        sections = _rules_help_sections()
        split_idx = 5
        left_sections = sections[:split_idx]
        right_sections = sections[split_idx:]

        col_gap = 26
        col_width = (pw - 56 - col_gap) / 2
        left_x = margin + 24
        right_x = left_x + col_width + col_gap
        start_y = panel_top - 20

        y = start_y
        for icon_key, title, lines in left_sections:
            y = self._draw_section(left_x, y, col_width, icon_key, title, lines)

        y = start_y
        for icon_key, title, lines in right_sections:
            y = self._draw_section(right_x, y, col_width, icon_key, title, lines)

        self._ui.draw()
