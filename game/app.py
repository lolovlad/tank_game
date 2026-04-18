from __future__ import annotations

import math
import random
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import arcade
import arcade.gui
from arcade.types.rect import XYWH

from .assets import ensure_assets, get_asset_path, resolve_pickup_texture_path
from .config import GRID_COLS, GRID_ROWS, SCREEN_HEIGHT, SCREEN_TITLE, SCREEN_WIDTH, SERVER_PORT, TILE_SIZE
from .level import (
    ArenaLevel,
    BREAKABLE,
    EMPTY,
    METAL,
    level_display_name,
    level_names,
    load_level,
    next_custom_level_name,
    save_level,
)
from .network import LobbyConfig, NetworkPeer
from .spawn_settings import DEFAULT_PICKUP_SPAWN_SETTINGS, PickupSpawnSettings

TEXTURE_CACHE: dict[str, arcade.Texture] = {}
TANK_TEXTURE_ANGLE_OFFSET = -90
TANK_TURN_INVERT_X = -1
TANK_TURN_INVERT_Y = 1
ROUND_COUNT = 5
ROUND_WIN_TARGET = 3
ROUND_RESTART_DELAY_SEC = 1.3


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
HUD_MAX_LIVES_DISPLAY = 5
HUD_ICON_SIZE = 28
HUD_LIFE_SPACING = 16
FIRE_COOLDOWN_SEC = 0.55
VISION_RADIUS_TILES = 10
VISION_RECALC_INTERVAL_SEC = 0.10
VISION_STEP_DIVISOR = 0.50
FLOOR_COLOR = (42, 42, 42, 255)
HUD_PANEL_HEIGHT = 68
HUD_PANEL_COLOR = (8, 12, 20, 235)
PICKUP_ICON_SIZE = 26
BULLET_ICON_SIZE = 10
# Полупроход по осям для стен и столкновения танк–танк (согласовано с _position_collides_with_walls).
TANK_BODY_HALF = 12

NET_MSG_LOBBY_HANDSHAKE = "lobby_handshake"
NET_MSG_REMATCH_READY = "rematch_ready"
NET_MSG_REMATCH_START = "rematch_start"


@dataclass(frozen=True)
class LobbyHandshakeResult:
    level_name: str
    your_slot: int
    session_id: str | None


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


def texture_for(asset_name: str) -> arcade.Texture | None:
    path = get_asset_path(asset_name)
    if not path:
        return None
    key = str(path)
    cached = TEXTURE_CACHE.get(key)
    if cached:
        return cached
    loaded = arcade.load_texture(key)
    TEXTURE_CACHE[key] = loaded
    return loaded


def texture_from_path(path: Path | None) -> arcade.Texture | None:
    if path is None or not path.exists():
        return None
    key = str(path.resolve())
    cached = TEXTURE_CACHE.get(key)
    if cached:
        return cached
    loaded = arcade.load_texture(key)
    TEXTURE_CACHE[key] = loaded
    return loaded


def pickup_texture_for(kind: str) -> arcade.Texture | None:
    return texture_from_path(resolve_pickup_texture_path(kind))


class LevelRenderCache:
    def __init__(self, level: ArenaLevel, draw_empty_grid: bool) -> None:
        self.level = level
        self.draw_empty_grid = draw_empty_grid
        self.breakable_sprites = arcade.SpriteList()
        self.metal_sprites = arcade.SpriteList()
        self.grid_lines: list[tuple[float, float, float, float]] = []
        self.fallback_tiles: list[tuple[float, float, int]] = []
        self.dirty = True

    def mark_dirty(self) -> None:
        self.dirty = True

    def rebuild(self) -> None:
        self.breakable_sprites = arcade.SpriteList()
        self.metal_sprites = arcade.SpriteList()
        self.grid_lines = []
        self.fallback_tiles = []

        breakable_texture = texture_for("wall_breakable")
        metal_texture = texture_for("wall_metal")

        for row in range(self.level.rows):
            for col in range(self.level.cols):
                x, y = tile_to_xy(col, row)
                cell = self.level.grid[row][col]
                if cell == BREAKABLE:
                    if breakable_texture:
                        sprite = arcade.Sprite(path_or_texture=breakable_texture, center_x=x, center_y=y, scale=1.0)
                        sprite.width = TILE_SIZE
                        sprite.height = TILE_SIZE
                        self.breakable_sprites.append(sprite)
                    else:
                        self.fallback_tiles.append((x, y, BREAKABLE))
                elif cell == METAL:
                    if metal_texture:
                        sprite = arcade.Sprite(path_or_texture=metal_texture, center_x=x, center_y=y, scale=1.0)
                        sprite.width = TILE_SIZE
                        sprite.height = TILE_SIZE
                        self.metal_sprites.append(sprite)
                    else:
                        self.fallback_tiles.append((x, y, METAL))

        if self.draw_empty_grid:
            width = self.level.cols * TILE_SIZE
            height = self.level.rows * TILE_SIZE
            color = arcade.color.DARK_SLATE_GRAY
            for col in range(self.level.cols + 1):
                x = col * TILE_SIZE
                self.grid_lines.append((x, 0, x, height))
            for row in range(self.level.rows + 1):
                y = row * TILE_SIZE
                self.grid_lines.append((0, y, width, y))

        self.dirty = False

    def draw(self) -> None:
        if self.dirty:
            self.rebuild()

        if self.draw_empty_grid:
            for x1, y1, x2, y2 in self.grid_lines:
                arcade.draw_line(x1, y1, x2, y2, arcade.color.DARK_SLATE_GRAY, 1)

        self.breakable_sprites.draw()
        self.metal_sprites.draw()

        for x, y, cell in self.fallback_tiles:
            left = x - TILE_SIZE * 0.5
            bottom = y - TILE_SIZE * 0.5
            if cell == BREAKABLE:
                arcade.draw_lbwh_rectangle_filled(left, bottom, TILE_SIZE, TILE_SIZE, arcade.color.BRICK_RED)
            elif cell == METAL:
                arcade.draw_lbwh_rectangle_filled(left, bottom, TILE_SIZE, TILE_SIZE, arcade.color.LIGHT_GRAY)


def tile_to_xy(col: int, row: int, origin_x: float = 0, origin_y: float = 0) -> tuple[float, float]:
    return origin_x + (col + 0.5) * TILE_SIZE, origin_y + (row + 0.5) * TILE_SIZE


def xy_to_tile(x: float, y: float, origin_x: float = 0, origin_y: float = 0) -> tuple[int, int]:
    return int((x - origin_x) // TILE_SIZE), int((y - origin_y) // TILE_SIZE)


@dataclass
class Tank:
    x: float
    y: float
    angle: float = 0
    hp: int = 3
    speed: float = 140
    fire_cooldown: float = 0.0
    ammo: int = 10
    speed_boost_timer: float = 0.0

    def move(self, dx: float, dy: float, dt: float, world_width: float, world_height: float) -> None:
        self.x += dx * self.speed * dt
        self.y += dy * self.speed * dt
        self.x = min(max(self.x, TILE_SIZE * 0.5), world_width - TILE_SIZE * 0.5)
        self.y = min(max(self.y, TILE_SIZE * 0.5), world_height - TILE_SIZE * 0.5)


@dataclass
class Bullet:
    x: float
    y: float
    dx: float
    dy: float
    owner_slot: int
    speed: float = 320
    alive: bool = True

    def update(self, dt: float) -> None:
        self.x += self.dx * self.speed * dt
        self.y += self.dy * self.speed * dt


@dataclass
class ExplosionParticle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float


class ExplosionBurst:
    """Короткая анимация искр при попадании снаряда."""

    __slots__ = ("particles",)

    def __init__(self, x: float, y: float, intensity: float = 1.0) -> None:
        self.particles: list[ExplosionParticle] = []
        n = max(10, int(24 * intensity))
        for _ in range(n):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(90.0, 300.0)
            life = random.uniform(0.16, 0.45)
            self.particles.append(ExplosionParticle(x, y, math.cos(ang) * sp, math.sin(ang) * sp, life, life))

    def update(self, dt: float) -> bool:
        alive: list[ExplosionParticle] = []
        for p in self.particles:
            p.life -= dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx *= 0.91
            p.vy *= 0.91
            if p.life > 0:
                alive.append(p)
        self.particles = alive
        return len(self.particles) > 0

    def draw(self, is_visible: Callable[[float, float], bool] | None = None) -> None:
        for p in self.particles:
            if is_visible is not None and not is_visible(p.x, p.y):
                continue
            t = p.life / p.max_life if p.max_life > 0 else 0.0
            alpha = int(255 * min(1.0, t * 1.25))
            r = 255
            g = int(70 + 150 * t)
            b = int(25 * (1.0 - t))
            size = 2.0 + 5.0 * (1.0 - t)
            arcade.draw_circle_filled(p.x, p.y, size, (r, g, b, alpha))


@dataclass
class Pickup:
    kind: str
    col: int
    row: int

    def to_dict(self) -> dict[str, int | str]:
        return {"kind": self.kind, "col": self.col, "row": self.row}


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
        self._add_button("Редактор уровней", lambda _: self.window.show_view(LevelEditorView()))
        self._add_button("Настройки", lambda _: self.window.show_view(SettingsView()))
        self._add_button("Выход", lambda _: arcade.exit())
        self.mount_centered()

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=360)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_MIDNIGHT_BLUE)
        self.ui.draw()


class ArenaSelectView(BaseUI):
    def __init__(self, mode: str, title: str) -> None:
        super().__init__()
        self.mode = mode
        self.title = title
        self.setup()

    def setup(self) -> None:
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
        self.window.show_view(GameView(mode=self.mode, level_name=arena_name))

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=360)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_SLATE_BLUE)
        self.ui.draw()


class ModeSelectView(BaseUI):
    def __init__(self) -> None:
        super().__init__()
        self.setup()

    def setup(self) -> None:
        self.v_box.add(arcade.gui.UILabel(text="Режимы локальной игры", font_size=28))
        self._add_button("Человек vs Человек", lambda _: self.window.show_view(GameView(mode="local")))
        self._add_button("Назад", lambda _: self.window.show_view(MainMenuView()))
        self.mount_centered()

    def _add_button(self, text: str, callback) -> None:
        button = arcade.gui.UIFlatButton(text=text, width=300)
        button.on_click = callback
        self.v_box.add(button)

    def on_draw(self) -> None:
        self.clear(color=arcade.color.DARK_SLATE_BLUE)
        self.ui.draw()


class SettingsView(BaseUI):
    def __init__(self) -> None:
        super().__init__()
        self.music = False
        self.sfx = True
        self.setup()

    def setup(self) -> None:
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


class MatchEndView(BaseUI):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.setup()

    def setup(self) -> None:
        self.v_box.add(arcade.gui.UILabel(text=self.title, font_size=40, width=520, align="center"))
        self.v_box.add(arcade.gui.UILabel(text=self.subtitle, font_size=18, width=520, align="center"))
        self._add_button("Сыграть снова", lambda _: self.window.show_view(ArenaSelectView(mode="local", title="Выбор арены: локальная дуэль")))
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
                    self.status_label.text = "Игрок подключился к реваншу. Нажмите «Сыграть снова», если ещё не нажато."
                self._try_start_as_host()
            elif msg_type == NET_MSG_REMATCH_START and self.mode == "online_client" and self._session_matches(msg):
                self._start_new_match()

    def on_draw(self) -> None:
        self.clear(color=arcade.color.BLACK)
        self.ui.draw()


class LobbyView(BaseUI):
    """Хаб онлайна: арену выбирает только создатель лобби; гость подключается без выбора карты."""

    def __init__(self) -> None:
        super().__init__()
        self.setup()

    def setup(self) -> None:
        self.v_box.add(arcade.gui.UILabel(text="Сетевое лобби", font_size=28))
        self.v_box.add(
            arcade.gui.UILabel(
                text="Создатель лобби выбирает арену. Подключающийся игрок получит ту же карту от хоста.",
                font_size=13,
                width=560,
                align="center",
            )
        )
        self._add_button(
            "Создать лобби",
            lambda _: self.window.show_view(ArenaSelectView(mode="online_host", title="Выбор арены для лобби")),
        )
        self._add_button("Подключиться к лобби", lambda _: self.window.show_view(ClientConnectView()))
        self._add_button("Назад", lambda _: self.window.show_view(MainMenuView()))
        self.mount_centered()

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
        self.status = arcade.gui.UILabel(text="Запуск сервера…", font_size=14, width=640, align="center", text_color=arcade.color.LIGHT_GRAY)
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
        self.v_box.add(arcade.gui.UILabel(text="Введите адрес хоста и порт (как на экране ожидания у создателя лобби).", font_size=13, width=520, align="center"))
        self.v_box.add(arcade.gui.UILabel(text="IP или имя хоста", font_size=12, width=400, align="left"))
        self.host_field = arcade.gui.UIInputText(width=400, height=32, text="127.0.0.1", font_size=14)
        self.v_box.add(self.host_field)
        self.v_box.add(arcade.gui.UILabel(text="Порт", font_size=12, width=400, align="left"))
        self.port_field = arcade.gui.UIInputText(width=400, height=32, text=str(SERVER_PORT), font_size=14)
        self.v_box.add(self.port_field)
        self.status = arcade.gui.UILabel(text="", font_size=13, width=520, align="center", text_color=arcade.color.ORANGE_PEEL)
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


class LevelEditorView(arcade.View):
    PAINT_BREAKABLE = "breakable"
    PAINT_METAL = "metal"
    PAINT_SPAWN_1 = "spawn_1"
    PAINT_SPAWN_2 = "spawn_2"
    PAINT_ERASE = "erase"

    def __init__(self) -> None:
        super().__init__()
        self.level_name = next_custom_level_name("custom_arena")
        self.level = load_level(self.level_name)
        self.level_renderer = LevelRenderCache(self.level, draw_empty_grid=True)
        self.paint_mode = self.PAINT_BREAKABLE
        self.info = "ЛКМ: применить, ПКМ: очистить, 1/2/3/4/0 - кисти, S: сохранить, R: сброс, ESC: меню"
        self.fps = 0.0
        self.reset_button_bounds: tuple[float, float, float, float] | None = None

    def on_show_view(self) -> None:
        # In editor we need extra width for the right panel.
        self.window.set_size(SCREEN_WIDTH, SCREEN_HEIGHT)

    def on_draw(self) -> None:
        self.clear(arcade.color.BLACK)
        self.level_renderer.draw()
        draw_spawn_markers(self.level)
        map_width = self.level.cols * TILE_SIZE
        panel_x = map_width + 8
        panel_width = SCREEN_WIDTH - panel_x - 8
        arcade.draw_lbwh_rectangle_filled(panel_x, 8, panel_width, SCREEN_HEIGHT - 16, arcade.color.DARK_BLUE_GRAY)
        arcade.draw_lbwh_rectangle_outline(panel_x, 8, panel_width, SCREEN_HEIGHT - 16, arcade.color.WHITE, 1)
        arcade.draw_text("Палитра редактора", panel_x + 10, SCREEN_HEIGHT - 36, arcade.color.WHITE, 14)
        arcade.draw_text(f"Имя карты: {level_display_name(self.level_name)}", panel_x + 10, SCREEN_HEIGHT - 58, arcade.color.LIGHT_GRAY, 12)

        palette_items = [
            ("1", "Кирпич: бесконечно", self.PAINT_BREAKABLE),
            ("2", "Металл: бесконечно", self.PAINT_METAL),
            ("3", "Мой танк: 1 шт", self.PAINT_SPAWN_1),
            ("4", "Вражеский танк: 1 шт", self.PAINT_SPAWN_2),
            ("0", "Ластик", self.PAINT_ERASE),
        ]
        y = SCREEN_HEIGHT - 72
        for hotkey, text, mode in palette_items:
            color = arcade.color.YELLOW if self.paint_mode == mode else arcade.color.WHITE
            arcade.draw_text(f"[{hotkey}] {text}", panel_x + 10, y, color, 13)
            y -= 26

        arcade.draw_text("Поле окружено металлом", panel_x + 10, y - 6, arcade.color.LIGHT_GRAY, 11)
        arcade.draw_text(self.info, 10, SCREEN_HEIGHT - 22, arcade.color.WHITE, 12)
        arcade.draw_text(f"FPS: {self.fps:5.1f}", panel_x + 10, 18, arcade.color.LIGHT_GREEN, 13)
        button_x = panel_x + 10
        button_y = 50
        button_w = max(120, panel_width - 20)
        button_h = 34
        self.reset_button_bounds = (button_x, button_y, button_w, button_h)
        arcade.draw_lbwh_rectangle_filled(button_x, button_y, button_w, button_h, arcade.color.DARK_RED)
        arcade.draw_lbwh_rectangle_outline(button_x, button_y, button_w, button_h, arcade.color.WHITE, 1)
        arcade.draw_text("Сбросить поле", button_x + 12, button_y + 9, arcade.color.WHITE, 12)

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> None:
        if button == arcade.MOUSE_BUTTON_LEFT and self.reset_button_bounds:
            bx, by, bw, bh = self.reset_button_bounds
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self.reset_level()
                return
        self._paint_at(x, y, button)

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int) -> None:
        if buttons & arcade.MOUSE_BUTTON_LEFT:
            self._paint_at(x, y, arcade.MOUSE_BUTTON_LEFT)
        if buttons & arcade.MOUSE_BUTTON_RIGHT:
            self._paint_at(x, y, arcade.MOUSE_BUTTON_RIGHT)

    def _paint_at(self, x: float, y: float, button: int) -> None:
        col, row = xy_to_tile(x, y)
        if not (0 <= row < self.level.rows and 0 <= col < self.level.cols):
            return
        if col == 0 or col == self.level.cols - 1 or row == 0 or row == self.level.rows - 1:
            return

        if button == arcade.MOUSE_BUTTON_RIGHT:
            self.level.grid[row][col] = EMPTY
            self.level_renderer.mark_dirty()
            return

        if button != arcade.MOUSE_BUTTON_LEFT:
            return

        if self.paint_mode == self.PAINT_BREAKABLE:
            self.level.grid[row][col] = BREAKABLE
        elif self.paint_mode == self.PAINT_METAL:
            self.level.grid[row][col] = METAL
        elif self.paint_mode == self.PAINT_ERASE:
            self.level.grid[row][col] = EMPTY
        elif self.paint_mode == self.PAINT_SPAWN_1:
            self.level.spawn_1 = (col, row)
            self.level.grid[row][col] = EMPTY
        elif self.paint_mode == self.PAINT_SPAWN_2:
            self.level.spawn_2 = (col, row)
            self.level.grid[row][col] = EMPTY
        self.level_renderer.mark_dirty()

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key in {arcade.key.KEY_1, arcade.key.NUM_1}:
            self.paint_mode = self.PAINT_BREAKABLE
        elif key in {arcade.key.KEY_2, arcade.key.NUM_2}:
            self.paint_mode = self.PAINT_METAL
        elif key in {arcade.key.KEY_3, arcade.key.NUM_3}:
            self.paint_mode = self.PAINT_SPAWN_1
        elif key in {arcade.key.KEY_4, arcade.key.NUM_4}:
            self.paint_mode = self.PAINT_SPAWN_2
        elif key in {arcade.key.KEY_0, arcade.key.NUM_0}:
            self.paint_mode = self.PAINT_ERASE
        elif key == arcade.key.S:
            save_level(self.level)
        elif key == arcade.key.R:
            self.reset_level()
        elif key == arcade.key.ESCAPE:
            self.window.show_view(MainMenuView())

    def on_update(self, delta_time: float) -> None:
        if delta_time > 0:
            current = 1.0 / delta_time
            self.fps = current if self.fps == 0 else (self.fps * 0.9 + current * 0.1)

    def reset_level(self) -> None:
        self.level = ArenaLevel.empty(self.level_name)
        self.level_renderer = LevelRenderCache(self.level, draw_empty_grid=True)
        self.level_renderer.mark_dirty()


class GameView(arcade.View):
    def __init__(
        self,
        mode: str,
        level_name: str = "classic_arena",
        network_peer: NetworkPeer | None = None,
        network_session_id: str | None = None,
        network_my_slot: int | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.level_name = level_name
        self.level = load_level(level_name)
        self._initial_level_grid = [row[:] for row in self.level.grid]
        p1 = tile_to_xy(*self.level.spawn_1)
        p2 = tile_to_xy(*self.level.spawn_2)
        self.player_1 = Tank(*p1)
        self.player_2 = Tank(*p2)
        self.spawn_settings: PickupSpawnSettings = DEFAULT_PICKUP_SPAWN_SETTINGS
        self.player_1.ammo = self.spawn_settings.initial_ammo
        self.player_2.ammo = self.spawn_settings.initial_ammo
        self.bullets: list[Bullet] = []
        self.pickups: list[Pickup] = []
        self.explosions: list[ExplosionBurst] = []
        self._pickup_spawn_timers: dict[str, float] = {
            "ammo": self.spawn_settings.ammo_spawn_interval_sec,
            "hp": self.spawn_settings.hp_spawn_interval_sec,
            "speed": self.spawn_settings.speed_spawn_interval_sec,
        }
        self.keys: set[int] = set()
        self.peer: NetworkPeer | None = None
        self.status = "Игра началась"
        self.host_authoritative = mode == "online_host"
        self.world_width = self.level.cols * TILE_SIZE
        self.world_height = self.level.rows * TILE_SIZE
        self.level_renderer = LevelRenderCache(self.level, draw_empty_grid=False)
        self.fps = 0.0
        self.round_number = 1
        self.score_p1 = 0
        self.score_p2 = 0
        self.round_over = False
        self.round_restart_timer = 0.0
        self.match_over = False
        self.visible_cells: set[tuple[int, int]] = set()
        self.fog_sprites = arcade.SpriteList()
        self._vision_recalc_timer = 0.0
        self._last_vision_source_tiles: tuple[tuple[int, int], ...] = ()
        self._fog_dirty = True
        if mode == "online_host":
            self.network_my_slot = network_my_slot if network_my_slot is not None else 1
            self.network_session_id = network_session_id or str(uuid.uuid4())
        elif mode == "online_client":
            self.network_my_slot = int(network_my_slot) if network_my_slot is not None else 2
            self.network_session_id = network_session_id
        else:
            self.network_my_slot = 0
            self.network_session_id = None
        self._net_cell_queue: list[list[int]] = []
        self._net_fire_queue_send: list[dict] = []
        self._net_fire_seq = 0
        self._net_seen_remote_fire: dict[str, int] = {}
        self._remote_inp_dx = 0.0
        self._remote_inp_dy = 0.0
        self._setup_network(network_peer)
        self._recalculate_visibility(force=True)

    def on_show_view(self) -> None:
        # In gameplay the map should fill the window without extra side space.
        self.window.set_size(self.world_width, SCREEN_HEIGHT)

    def _setup_network(self, existing_peer: NetworkPeer | None = None) -> None:
        if self.mode not in {"online_host", "online_client"}:
            return
        if existing_peer is not None:
            self.peer = existing_peer
            self.status = "Игра по сети"
            return
        self.peer = NetworkPeer()
        cfg = LobbyConfig(host="127.0.0.1", port=SERVER_PORT)
        try:
            if self.mode == "online_host":
                self.peer.host(cfg)
                self.status = f"Лобби создано: 127.0.0.1:{SERVER_PORT}"
            else:
                self.peer.join(cfg)
                self.status = f"Подключено к 127.0.0.1:{SERVER_PORT}"
        except OSError:
            self.status = "Сеть недоступна: запустите host перед client"

    def on_draw(self) -> None:
        self.clear(arcade.color.BLACK)
        arcade.draw_lbwh_rectangle_filled(0, 0, self.world_width, self.world_height, FLOOR_COLOR)
        self.level_renderer.draw()
        self._draw_pickups()
        self._draw_tank(self.player_1, arcade.color.YELLOW_ORANGE, "tank_player")
        self._draw_tank(self.player_2, arcade.color.GRAY_BLUE, "tank_enemy")
        for bullet in self.bullets:
            bt = texture_for("bullet")
            if bt:
                arcade.draw_texture_rect(bt, XYWH(bullet.x, bullet.y, BULLET_ICON_SIZE, BULLET_ICON_SIZE), angle=0)
            else:
                arcade.draw_circle_filled(bullet.x, bullet.y, 4, arcade.color.RED_ORANGE)
        self._draw_fog_of_war()
        self._draw_speed_boost_particles(self.player_1, arcade.color.YELLOW)
        self._draw_speed_boost_particles(self.player_2, arcade.color.SKY_BLUE)
        self._draw_explosions()
        self._draw_match_hud()

    def _draw_hud_tank_icon(self, center_x: float, center_y: float, asset_name: str, fallback_color: arcade.Color) -> None:
        texture = texture_for(asset_name)
        if texture:
            arcade.draw_texture_rect(
                texture,
                XYWH(center_x, center_y, HUD_ICON_SIZE, HUD_ICON_SIZE),
                angle=TANK_TEXTURE_ANGLE_OFFSET,
            )
        else:
            arcade.draw_rect_filled(XYWH(center_x, center_y, HUD_ICON_SIZE - 4, HUD_ICON_SIZE - 4), fallback_color, tilt_angle=0)

    def _draw_hud_life_pips(self, anchor_x: float, center_y: float, hp: int, align_right: bool) -> None:
        hp = max(0, min(HUD_MAX_LIVES_DISPLAY, hp))
        for i in range(HUD_MAX_LIVES_DISPLAY):
            offset = i * HUD_LIFE_SPACING
            cx = anchor_x - offset if align_right else anchor_x + offset
            filled = i < hp
            fill_color = arcade.color.RED if filled else arcade.color.DARK_GRAY
            arcade.draw_circle_filled(cx, center_y, 6, fill_color)
            arcade.draw_circle_outline(cx, center_y, 6, arcade.color.WHITE, 1)

    def _draw_reload_meter(self, left: float, bottom: float, width: float, height: float, cooldown: float) -> None:
        arcade.draw_lbwh_rectangle_filled(left, bottom, width, height, (22, 22, 22, 220))
        arcade.draw_lbwh_rectangle_outline(left, bottom, width, height, arcade.color.GRAY, 1)
        ready_ratio = 1.0 - max(0.0, min(1.0, cooldown / FIRE_COOLDOWN_SEC))
        fill_width = max(0.0, width * ready_ratio)
        fill_color = arcade.color.APPLE_GREEN if ready_ratio >= 0.999 else arcade.color.ORANGE
        if fill_width > 0:
            arcade.draw_lbwh_rectangle_filled(left, bottom, fill_width, height, fill_color)

    def _draw_pickups(self) -> None:
        for pickup in self.pickups:
            x, y = tile_to_xy(pickup.col, pickup.row)
            tex = pickup_texture_for(pickup.kind)
            if tex:
                arcade.draw_texture_rect(tex, XYWH(x, y, PICKUP_ICON_SIZE, PICKUP_ICON_SIZE), angle=0)
            else:
                if pickup.kind == "ammo":
                    color = arcade.color.GOLD
                elif pickup.kind == "hp":
                    color = arcade.color.APPLE_GREEN
                else:
                    color = arcade.color.SKY_BLUE
                r = PICKUP_ICON_SIZE * 0.35
                arcade.draw_circle_filled(x, y, r, color)
                arcade.draw_circle_outline(x, y, r, arcade.color.BLACK, 1)

    def _draw_explosions(self) -> None:
        vis = self._world_point_visible_in_fog
        for burst in self.explosions:
            burst.draw(vis)

    def _spawn_explosion(self, x: float, y: float, intensity: float = 1.0) -> None:
        self.explosions.append(ExplosionBurst(x, y, intensity))

    def _update_explosions(self, dt: float) -> None:
        alive: list[ExplosionBurst] = []
        for burst in self.explosions:
            if burst.update(dt):
                alive.append(burst)
        self.explosions = alive

    def _draw_speed_boost_particles(self, tank: Tank, color: arcade.Color) -> None:
        if tank.speed_boost_timer <= 0:
            return
        vis = self._world_point_visible_in_fog
        phase = time.monotonic() * 8.0
        for i in range(8):
            ang = phase + i * (math.tau / 8.0)
            radius = 20.0 + (i % 2) * 2.5
            px = tank.x + math.cos(ang) * radius
            py = tank.y + math.sin(ang) * radius
            if not vis(px, py):
                continue
            arcade.draw_circle_filled(px, py, 2.2, color)

    def _draw_match_hud(self) -> None:
        arcade.draw_lbwh_rectangle_filled(0, SCREEN_HEIGHT - HUD_PANEL_HEIGHT, self.world_width, HUD_PANEL_HEIGHT, HUD_PANEL_COLOR)
        arcade.draw_lbwh_rectangle_outline(
            0,
            SCREEN_HEIGHT - HUD_PANEL_HEIGHT,
            self.world_width,
            HUD_PANEL_HEIGHT,
            arcade.color.SLATE_GRAY,
            2,
        )
        margin = 14.0
        row_y = SCREEN_HEIGHT - 34.0
        mid_x = self.world_width * 0.5

        # Игрок 1: иконка танка + жизни справа от неё
        p1_tank_x = margin + HUD_ICON_SIZE * 0.5
        self._draw_hud_tank_icon(p1_tank_x, row_y, "tank_player", arcade.color.YELLOW_ORANGE)
        pips_start = p1_tank_x + HUD_ICON_SIZE * 0.5 + 10
        self._draw_hud_life_pips(pips_start, row_y, self.player_1.hp, align_right=False)
        self._draw_reload_meter(margin, row_y - 22, 130, 8, self.player_1.fire_cooldown)
        arcade.draw_text(f"{self.player_1.ammo}", margin + 136, row_y - 26, arcade.color.GOLD, 13)

        # Игрок 2: жизни слева от иконки, иконка у правого края
        p2_tank_x = self.world_width - margin - HUD_ICON_SIZE * 0.5
        pips_anchor = p2_tank_x - HUD_ICON_SIZE * 0.5 - 10
        self._draw_hud_life_pips(pips_anchor, row_y, self.player_2.hp, align_right=True)
        self._draw_hud_tank_icon(p2_tank_x, row_y, "tank_enemy", arcade.color.GRAY_BLUE)
        self._draw_reload_meter(self.world_width - margin - 130, row_y - 22, 130, 8, self.player_2.fire_cooldown)
        arcade.draw_text(
            f"{self.player_2.ammo}",
            self.world_width - margin - 136,
            row_y - 26,
            arcade.color.GOLD,
            13,
            anchor_x="right",
        )

        # По центру: только счёт матча без лишних подписей.
        arcade.draw_text(
            f"{self.score_p1}  :  {self.score_p2}",
            mid_x,
            SCREEN_HEIGHT - 38,
            arcade.color.WHITE,
            20,
            bold=True,
            anchor_x="center",
        )

    def _vision_sources(self) -> list[Tank]:
        """Туман считается только на этом ПК: в онлайне — от своего танка (без синхронизации тумана по сети)."""
        if self.mode == "local":
            return [self.player_1, self.player_2]
        if self.mode == "online_client":
            return [self._network_controlled_tank()]
        return [self.player_1]

    def _mark_visibility_dirty(self) -> None:
        self._fog_dirty = True
        self._vision_recalc_timer = 0.0

    def _rebuild_fog_sprites(self) -> None:
        self.fog_sprites = arcade.SpriteList()
        hidden_tiles = 0
        for row in range(self.level.rows):
            for col in range(self.level.cols):
                if (col, row) in self.visible_cells:
                    continue
                sprite = arcade.SpriteSolidColor(TILE_SIZE, TILE_SIZE, (32, 32, 38, 255))
                sprite.center_x, sprite.center_y = tile_to_xy(col, row)
                self.fog_sprites.append(sprite)
                hidden_tiles += 1
        if hidden_tiles == 0:
            self.fog_sprites = arcade.SpriteList()

    def _recalculate_visibility(self, force: bool = False) -> None:
        source_tiles = tuple(xy_to_tile(tank.x, tank.y) for tank in self._vision_sources())
        if not force and not self._fog_dirty and source_tiles == self._last_vision_source_tiles:
            return
        cells: set[tuple[int, int]] = set()
        radius = VISION_RADIUS_TILES
        radius_sq = (radius * TILE_SIZE) ** 2
        for tank in self._vision_sources():
            tank_col, tank_row = xy_to_tile(tank.x, tank.y)
            for row in range(max(0, tank_row - radius), min(self.level.rows, tank_row + radius + 1)):
                for col in range(max(0, tank_col - radius), min(self.level.cols, tank_col + radius + 1)):
                    cx, cy = tile_to_xy(col, row)
                    if distance_sq(tank.x, tank.y, cx, cy) > radius_sq:
                        continue
                    if self._has_line_of_sight(tank.x, tank.y, cx, cy):
                        cells.add((col, row))
        cells = self._expand_visibility_to_adjacent_walls(cells)
        self.visible_cells = cells
        self._last_vision_source_tiles = source_tiles
        self._fog_dirty = False
        self._rebuild_fog_sprites()

    def _world_point_visible_in_fog(self, x: float, y: float) -> bool:
        """Локально для этого окна: видна ли точка в твоём тумане (как для эффектов, так и для слоя тумана)."""
        if not self.visible_cells:
            return False
        col, row = xy_to_tile(x, y)
        if not (0 <= row < self.level.rows and 0 <= col < self.level.cols):
            return False
        return (col, row) in self.visible_cells

    def _draw_fog_of_war(self) -> None:
        if not self.visible_cells:
            arcade.draw_lbwh_rectangle_filled(0, 0, self.world_width, self.world_height, (28, 28, 34, 255))
            return
        self.fog_sprites.draw()

    def _visual_angle(self, tank: Tank) -> float:
        rad = math.radians(tank.angle)
        vx = math.cos(rad) * TANK_TURN_INVERT_X
        vy = math.sin(rad) * TANK_TURN_INVERT_Y
        return math.degrees(math.atan2(vy, vx)) + TANK_TEXTURE_ANGLE_OFFSET

    def _draw_tank(self, tank: Tank, fallback_color: arcade.Color, asset_name: str) -> None:
        texture = texture_for(asset_name)
        if texture:
            arcade.draw_texture_rect(texture, XYWH(tank.x, tank.y, 34, 34), angle=self._visual_angle(tank))
        else:
            arcade.draw_rect_filled(XYWH(tank.x, tank.y, 30, 30), fallback_color, tilt_angle=tank.angle)

    def _network_controlled_tank(self) -> Tank:
        """Какой танк ведёт этот клиент по TCP (слот 1 — хост/spawn_1, слот 2 — гость/spawn_2)."""
        if self.mode == "online_host":
            return self.player_1
        if self.mode == "online_client":
            return self.player_2 if self.network_my_slot == 2 else self.player_1
        raise RuntimeError("_network_controlled_tank только для online_*")

    def _local_wasd_tank(self) -> Tank:
        """WASD и Space: в онлайне — по слоту из лобби; локально — танк 1."""
        if self.mode in {"online_host", "online_client"}:
            return self._network_controlled_tank()
        return self.player_1

    def on_key_press(self, key: int, modifiers: int) -> None:
        self.keys.add(key)
        can_fire = (not self.round_over) and (not self.match_over) and self.player_1.hp > 0 and self.player_2.hp > 0
        if key == arcade.key.SPACE and can_fire:
            self._try_fire(self._local_wasd_tank())
        if self.mode == "local" and key in {arcade.key.RCTRL, arcade.key.LCTRL} and can_fire:
            self._try_fire(self.player_2)
        if key == arcade.key.ESCAPE:
            if self.peer:
                self.peer.close()
            self.window.show_view(MainMenuView())

    def on_key_release(self, key: int, modifiers: int) -> None:
        self.keys.discard(key)

    def _try_fire(self, tank: Tank) -> bool:
        if tank.fire_cooldown > 0 or tank.ammo <= 0:
            return False
        slot = 1 if tank is self.player_1 else 2
        angle = math.radians(tank.angle)
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        muzzle_offset = TILE_SIZE * 0.7
        spawn_x = tank.x + direction_x * muzzle_offset
        spawn_y = tank.y + direction_y * muzzle_offset
        self._spawn_bullet_at(slot, spawn_x, spawn_y, direction_x, direction_y)
        tank.ammo -= 1
        tank.fire_cooldown = FIRE_COOLDOWN_SEC
        if self.mode in {"online_host", "online_client"}:
            self._net_fire_seq += 1
            self._net_fire_queue_send.append(
                {
                    "from": self._my_net_fire_origin(),
                    "slot": slot,
                    "sx": spawn_x,
                    "sy": spawn_y,
                    "dx": direction_x,
                    "dy": direction_y,
                    "seq": self._net_fire_seq,
                }
            )
        return True

    def _my_net_fire_origin(self) -> str:
        return "host" if self.mode == "online_host" else "client"

    def _spawn_bullet_at(self, owner_slot: int, spawn_x: float, spawn_y: float, direction_x: float, direction_y: float) -> None:
        self.bullets.append(Bullet(spawn_x, spawn_y, direction_x, direction_y, owner_slot=owner_slot))

    def _set_tank_heading(self, tank: Tank, dx: float, dy: float) -> None:
        if dx or dy:
            tank.angle = math.degrees(math.atan2(dy, dx))

    def _cell_walkable(self, col: int, row: int) -> bool:
        if not (0 <= row < self.level.rows and 0 <= col < self.level.cols):
            return False
        return self.level.grid[row][col] == EMPTY

    def _position_collides_with_walls(self, x: float, y: float) -> bool:
        half_size = TANK_BODY_HALF
        for px in (x - half_size, x + half_size):
            for py in (y - half_size, y + half_size):
                col, row = xy_to_tile(px, py)
                if not self._cell_walkable(col, row):
                    return True
        return False

    def _tank_boxes_overlap_at(self, ax: float, ay: float, bx: float, by: float) -> bool:
        h = TANK_BODY_HALF
        return abs(ax - bx) < 2 * h and abs(ay - by) < 2 * h

    def _move_tank_with_collision(self, tank: Tank, dx: float, dy: float, dt: float, other: Tank | None = None) -> None:
        if dx == 0 and dy == 0:
            return
        step = tank.speed * dt
        try_x = tank.x + dx * step
        try_y = tank.y + dy * step

        clamped_x = min(max(try_x, TILE_SIZE * 0.5), self.world_width - TILE_SIZE * 0.5)
        if not self._position_collides_with_walls(clamped_x, tank.y):
            if other is None or not self._tank_boxes_overlap_at(clamped_x, tank.y, other.x, other.y):
                tank.x = clamped_x

        clamped_y = min(max(try_y, TILE_SIZE * 0.5), self.world_height - TILE_SIZE * 0.5)
        if not self._position_collides_with_walls(tank.x, clamped_y):
            if other is None or not self._tank_boxes_overlap_at(tank.x, clamped_y, other.x, other.y):
                tank.y = clamped_y


    def _has_line_of_sight(self, from_x: float, from_y: float, to_x: float, to_y: float) -> bool:
        distance = math.hypot(to_x - from_x, to_y - from_y)
        if distance <= 1:
            return True
        steps = max(1, int(distance / (TILE_SIZE * VISION_STEP_DIVISOR)))
        target_col, target_row = xy_to_tile(to_x, to_y)
        for i in range(1, steps):
            t = i / steps
            sample_x = from_x + (to_x - from_x) * t
            sample_y = from_y + (to_y - from_y) * t
            col, row = xy_to_tile(sample_x, sample_y)
            if not (0 <= row < self.level.rows and 0 <= col < self.level.cols):
                return False
            if col == target_col and row == target_row:
                continue
            if self.level.grid[row][col] != EMPTY:
                return False
        return True

    def _expand_visibility_to_adjacent_walls(self, visible: set[tuple[int, int]]) -> set[tuple[int, int]]:
        expanded = set(visible)
        for col, row in list(visible):
            for n_col, n_row in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if not (0 <= n_col < self.level.cols and 0 <= n_row < self.level.rows):
                    continue
                if self.level.grid[n_row][n_col] != EMPTY:
                    expanded.add((n_col, n_row))
        return expanded

    def _pickup_spawn_interval_for(self, kind: str) -> float:
        if kind == "ammo":
            return self.spawn_settings.ammo_spawn_interval_sec
        if kind == "hp":
            return self.spawn_settings.hp_spawn_interval_sec
        return self.spawn_settings.speed_spawn_interval_sec

    def _spawn_zone_for_kind(self, kind: str) -> tuple[int, int]:
        third = self.level.cols // 3
        if kind == "ammo":
            return 1, max(2, third)
        if kind == "hp":
            return max(1, third), max(third + 1, third * 2)
        return max(1, third * 2), max(third * 2 + 1, self.level.cols - 2)

    def _spawn_pickup(self, kind: str) -> None:
        kind_count = sum(1 for item in self.pickups if item.kind == kind)
        if kind_count >= self.spawn_settings.max_pickups_per_type:
            return
        occupied = {(item.col, item.row) for item in self.pickups}
        blocked = {self.level.spawn_1, self.level.spawn_2}
        candidates: list[tuple[int, int]] = []
        zone_start, zone_end = self._spawn_zone_for_kind(kind)
        min_pickup_dist_sq = float(self.spawn_settings.min_pickup_distance_tiles ** 2)
        min_tank_dist_sq = float(self.spawn_settings.min_distance_from_tanks_tiles ** 2)
        tank_tiles = (xy_to_tile(self.player_1.x, self.player_1.y), xy_to_tile(self.player_2.x, self.player_2.y))
        for row in range(1, self.level.rows - 1):
            for col in range(max(1, zone_start), min(self.level.cols - 1, zone_end + 1)):
                if self.level.grid[row][col] != EMPTY:
                    continue
                pos = (col, row)
                if pos in occupied or pos in blocked:
                    continue
                too_close_to_pickup = any(
                    distance_sq(col, row, item.col, item.row) < min_pickup_dist_sq for item in self.pickups
                )
                if too_close_to_pickup:
                    continue
                too_close_to_tank = any(distance_sq(col, row, t_col, t_row) < min_tank_dist_sq for t_col, t_row in tank_tiles)
                if too_close_to_tank:
                    continue
                candidates.append(pos)
        if not candidates:
            return
        col, row = max(
            candidates,
            key=lambda p: min(
                [distance_sq(p[0], p[1], item.col, item.row) for item in self.pickups]
                + [distance_sq(p[0], p[1], self.level.spawn_1[0], self.level.spawn_1[1])]
                + [distance_sq(p[0], p[1], self.level.spawn_2[0], self.level.spawn_2[1])]
            ),
        )
        self.pickups.append(Pickup(kind=kind, col=col, row=row))

    def _apply_pickup(self, tank: Tank, pickup_kind: str) -> None:
        if pickup_kind == "ammo":
            tank.ammo += self.spawn_settings.ammo_bonus
        elif pickup_kind == "hp":
            tank.hp = min(self.spawn_settings.max_hp, tank.hp + 1)
        elif pickup_kind == "speed":
            tank.speed_boost_timer = self.spawn_settings.speed_boost_duration_sec

    def _update_pickups(self, dt: float) -> None:
        if self.mode not in {"local", "online_host"}:
            return
        for kind in ("ammo", "hp", "speed"):
            self._pickup_spawn_timers[kind] -= dt
            if self._pickup_spawn_timers[kind] <= 0:
                self._pickup_spawn_timers[kind] = self._pickup_spawn_interval_for(kind)
                self._spawn_pickup(kind)

        for tank in (self.player_1, self.player_2):
            tank_col, tank_row = xy_to_tile(tank.x, tank.y)
            for pickup in list(self.pickups):
                if pickup.col == tank_col and pickup.row == tank_row:
                    self._apply_pickup(tank, pickup.kind)
                    self.pickups.remove(pickup)

    @staticmethod
    def _pack_tank_state(tank: Tank) -> dict[str, float | int]:
        return {"hp": int(tank.hp), "ammo": int(tank.ammo), "boost": float(tank.speed_boost_timer)}

    @staticmethod
    def _apply_tank_state(tank: Tank, payload: dict) -> None:
        tank.hp = max(0, min(DEFAULT_PICKUP_SPAWN_SETTINGS.max_hp, int(payload.get("hp", tank.hp))))
        tank.ammo = max(0, int(payload.get("ammo", tank.ammo)))
        tank.speed_boost_timer = max(0.0, float(payload.get("boost", tank.speed_boost_timer)))

    def _pack_pickups(self) -> list[dict[str, int | str]]:
        return [item.to_dict() for item in self.pickups]

    def _apply_pickups_payload(self, payload: list) -> None:
        parsed: list[Pickup] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", ""))
            if kind not in {"ammo", "hp", "speed"}:
                continue
            try:
                col = int(item.get("col", -1))
                row = int(item.get("row", -1))
            except (TypeError, ValueError):
                continue
            if 0 <= col < self.level.cols and 0 <= row < self.level.rows:
                parsed.append(Pickup(kind=kind, col=col, row=row))
        self.pickups = parsed

    def _update_speed_boosts(self, dt: float) -> None:
        if self.mode == "online_client":
            for tank in (self.player_1, self.player_2):
                tank.speed = 140 * (self.spawn_settings.speed_boost_multiplier if tank.speed_boost_timer > 0 else 1.0)
            return
        for tank in (self.player_1, self.player_2):
            if tank.speed_boost_timer > 0:
                tank.speed_boost_timer = max(0.0, tank.speed_boost_timer - dt)
            tank.speed = 140 * (self.spawn_settings.speed_boost_multiplier if tank.speed_boost_timer > 0 else 1.0)

    def on_update(self, delta_time: float) -> None:
        if delta_time > 0:
            current = 1.0 / delta_time
            self.fps = current if self.fps == 0 else (self.fps * 0.9 + current * 0.1)
        online = self.mode in {"online_host", "online_client"} and self.peer and self.peer.connected
        if self.mode == "online_host":
            self._remote_inp_dx = 0.0
            self._remote_inp_dy = 0.0
        if online:
            self._net_receive()
        if self.match_over:
            if online:
                self._net_send()
            return
        if self.round_over:
            if self.mode != "online_client":
                self.round_restart_timer -= delta_time
                if self.round_restart_timer <= 0:
                    self._advance_round_or_finish_match()
            if online:
                self._net_send()
            return
        self.player_1.fire_cooldown = max(0.0, self.player_1.fire_cooldown - delta_time)
        self.player_2.fire_cooldown = max(0.0, self.player_2.fire_cooldown - delta_time)
        self._update_speed_boosts(delta_time)
        self._update_explosions(delta_time)
        self._update_pickups(delta_time)
        self._update_players(delta_time)
        self._update_bullets(delta_time)
        self._resolve_collisions()
        self._vision_recalc_timer -= delta_time
        if self._vision_recalc_timer <= 0:
            self._vision_recalc_timer = VISION_RECALC_INTERVAL_SEC
            self._recalculate_visibility()
        if online:
            self._net_send()

    def _update_players(self, dt: float) -> None:
        dx1 = (1 if arcade.key.D in self.keys else 0) - (1 if arcade.key.A in self.keys else 0)
        dy1 = (1 if arcade.key.W in self.keys else 0) - (1 if arcade.key.S in self.keys else 0)
        if dx1 or dy1:
            length = math.hypot(dx1, dy1)
            dx1 /= length
            dy1 /= length

        if self.mode == "local":
            self._set_tank_heading(self.player_1, dx1, dy1)
            self._move_tank_with_collision(self.player_1, dx1, dy1, dt, self.player_2)
            dx2 = (1 if arcade.key.RIGHT in self.keys else 0) - (1 if arcade.key.LEFT in self.keys else 0)
            dy2 = (1 if arcade.key.UP in self.keys else 0) - (1 if arcade.key.DOWN in self.keys else 0)
            if dx2 or dy2:
                length = math.hypot(dx2, dy2)
                dx2 /= length
                dy2 /= length
            self._set_tank_heading(self.player_2, dx2, dy2)
            self._move_tank_with_collision(self.player_2, dx2, dy2, dt, self.player_1)
        elif self.mode == "online_client":
            return
        else:
            # online_host: игрок 1 — локально, игрок 2 — по вводу клиента (inp), симуляция только здесь
            self._set_tank_heading(self.player_1, dx1, dy1)
            self._move_tank_with_collision(self.player_1, dx1, dy1, dt, self.player_2)
            rdx, rdy = self._remote_inp_dx, self._remote_inp_dy
            self._set_tank_heading(self.player_2, rdx, rdy)
            self._move_tank_with_collision(self.player_2, rdx, rdy, dt, self.player_1)


    def _drain_peer_messages(self) -> list[dict]:
        if not self.peer:
            return []
        handshake: dict | None = None
        drained: list[dict] = []
        while True:
            m = self.peer.read()
            if m is None:
                break
            if m.get("type") == NET_MSG_LOBBY_HANDSHAKE:
                handshake = m
                continue
            drained.append(m)
        if handshake is not None:
            self.peer.push_front(handshake)
        return drained

    def _try_apply_remote_fire_dict(self, item: dict) -> None:
        origin = str(item.get("from", ""))
        if origin == self._my_net_fire_origin():
            return
        seq = int(item.get("seq", -1))
        if seq < 0:
            return
        prev = self._net_seen_remote_fire.get(origin, -1)
        if seq <= prev:
            return
        self._net_seen_remote_fire[origin] = seq
        slot = int(item.get("slot", 1))
        if slot not in (1, 2):
            slot = 1
        if self.mode == "online_host" and origin == "client":
            remote_tank = self.player_2 if slot == 2 else self.player_1
            if remote_tank.ammo <= 0 or remote_tank.fire_cooldown > 0:
                return
            remote_tank.ammo = max(0, remote_tank.ammo - 1)
            remote_tank.fire_cooldown = FIRE_COOLDOWN_SEC
        try:
            self._spawn_bullet_at(
                slot,
                float(item["sx"]),
                float(item["sy"]),
                float(item["dx"]),
                float(item["dy"]),
            )
        except (KeyError, TypeError, ValueError):
            return

    def _net_receive_host_batch(self, batch: list[dict]) -> None:
        latest_client: dict | None = None
        remote_fires: list[dict] = []
        for m in batch:
            if "x1" in m:
                continue
            for f in m.get("fires") or []:
                if isinstance(f, dict):
                    remote_fires.append(f)
            if "inp" in m or ("x" in m and "angle" in m):
                latest_client = m
        for f in remote_fires:
            self._try_apply_remote_fire_dict(f)
        if latest_client is not None:
            inp = latest_client.get("inp")
            if isinstance(inp, dict):
                try:
                    self._remote_inp_dx = float(inp.get("dx", 0.0))
                    self._remote_inp_dy = float(inp.get("dy", 0.0))
                except (TypeError, ValueError):
                    self._remote_inp_dx = 0.0
                    self._remote_inp_dy = 0.0
            elif "x" in latest_client and "angle" in latest_client:
                self.player_2.x = float(latest_client["x"])
                self.player_2.y = float(latest_client["y"])
                self.player_2.angle = float(latest_client["angle"])
            self.status = "Клиент подключен"

    def _net_receive_client_batch(self, batch: list[dict]) -> None:
        latest_host: dict | None = None
        remote_fires: list[dict] = []
        cell_batches: list[list[int]] = []
        for m in batch:
            if "x1" not in m:
                continue
            for row in m.get("cells") or []:
                if isinstance(row, (list, tuple)) and len(row) == 3:
                    cell_batches.append([int(row[0]), int(row[1]), int(row[2])])
            for f in m.get("fires") or []:
                if isinstance(f, dict):
                    remote_fires.append(f)
            latest_host = m
        for row, col, val in cell_batches:
            if 0 <= row < self.level.rows and 0 <= col < self.level.cols:
                self.level.grid[row][col] = int(val)
        if cell_batches:
            self.level_renderer.mark_dirty()
            self._mark_visibility_dirty()
        for f in remote_fires:
            self._try_apply_remote_fire_dict(f)
        if latest_host is not None:
            self.player_1.x = float(latest_host.get("x1", self.player_1.x))
            self.player_1.y = float(latest_host.get("y1", self.player_1.y))
            self.player_1.angle = float(latest_host.get("a1", self.player_1.angle))
            self.player_2.x = float(latest_host.get("x2", self.player_2.x))
            self.player_2.y = float(latest_host.get("y2", self.player_2.y))
            self.player_2.angle = float(latest_host.get("a2", self.player_2.angle))
            self._apply_tank_state(self.player_1, latest_host.get("p1", {}))
            self._apply_tank_state(self.player_2, latest_host.get("p2", {}))
            self._apply_pickups_payload(latest_host.get("pickups", []))
            if "score_p1" in latest_host:
                self.score_p1 = int(latest_host["score_p1"])
            if "score_p2" in latest_host:
                self.score_p2 = int(latest_host["score_p2"])
            if "round_number" in latest_host:
                new_rn = int(latest_host["round_number"])
                if new_rn != self.round_number and self.mode == "online_client":
                    self.level.grid = [row[:] for row in self._initial_level_grid]
                    self.level_renderer.mark_dirty()
                    self._mark_visibility_dirty()
                self.round_number = new_rn
            if "round_over" in latest_host:
                self.round_over = bool(latest_host["round_over"])
            if "round_restart_timer" in latest_host:
                self.round_restart_timer = float(latest_host["round_restart_timer"])
            if latest_host.get("match_over") and not self.match_over:
                self._show_match_end_screen()
            self.status = "Игра по сети активна"

    def _net_receive(self) -> None:
        if not self.peer or not self.peer.connected:
            return
        if self.mode not in {"online_host", "online_client"}:
            return
        batch = self._drain_peer_messages()
        if self.mode == "online_host":
            self._net_receive_host_batch(batch)
        else:
            self._net_receive_client_batch(batch)

    def _net_send_host(self) -> None:
        fires = self._net_fire_queue_send[:]
        self._net_fire_queue_send.clear()
        cells = self._net_cell_queue[:]
        self._net_cell_queue.clear()
        self.peer.send(
            {
                "x1": self.player_1.x,
                "y1": self.player_1.y,
                "a1": self.player_1.angle,
                "x2": self.player_2.x,
                "y2": self.player_2.y,
                "a2": self.player_2.angle,
                "cells": cells,
                "fires": fires,
                "p1": self._pack_tank_state(self.player_1),
                "p2": self._pack_tank_state(self.player_2),
                "pickups": self._pack_pickups(),
                "score_p1": self.score_p1,
                "score_p2": self.score_p2,
                "round_number": self.round_number,
                "round_over": self.round_over,
                "round_restart_timer": self.round_restart_timer,
                "match_over": self.match_over,
            }
        )

    def _net_send_client(self) -> None:
        fires = self._net_fire_queue_send[:]
        self._net_fire_queue_send.clear()
        dx = (1 if arcade.key.D in self.keys else 0) - (1 if arcade.key.A in self.keys else 0)
        dy = (1 if arcade.key.W in self.keys else 0) - (1 if arcade.key.S in self.keys else 0)
        if dx or dy:
            ln = math.hypot(dx, dy)
            dx /= ln
            dy /= ln
        self.peer.send({"inp": {"dx": float(dx), "dy": float(dy)}, "fires": fires})

    def _net_send(self) -> None:
        if not self.peer or not self.peer.connected:
            return
        if self.mode == "online_host":
            self._net_send_host()
        elif self.mode == "online_client":
            self._net_send_client()

    def _update_bullets(self, dt: float) -> None:
        for bullet in self.bullets:
            bullet.update(dt)
            if bullet.x < 0 or bullet.y < 0 or bullet.x > self.world_width or bullet.y > self.world_height:
                bx = min(max(bullet.x, 0.0), self.world_width)
                by = min(max(bullet.y, 0.0), self.world_height)
                self._spawn_explosion(bx, by, 0.6)
                bullet.alive = False
                continue
            col, row = xy_to_tile(bullet.x, bullet.y)
            if 0 <= row < self.level.rows and 0 <= col < self.level.cols:
                cell = self.level.grid[row][col]
                if cell == METAL:
                    self._spawn_explosion(bullet.x, bullet.y, 1.0)
                    bullet.alive = False
                elif cell == BREAKABLE:
                    self._spawn_explosion(bullet.x, bullet.y, 1.15)
                    bullet.alive = False
                    if self.mode == "online_client":
                        continue
                    self.level.grid[row][col] = EMPTY
                    self.level_renderer.mark_dirty()
                    self._mark_visibility_dirty()
                    if self.mode == "online_host":
                        self._net_cell_queue.append([row, col, EMPTY])
        self.bullets = [b for b in self.bullets if b.alive]

    def _resolve_collisions(self) -> None:
        if self.mode == "online_client":
            for bullet in self.bullets:
                if bullet.owner_slot != 1 and distance_sq(bullet.x, bullet.y, self.player_1.x, self.player_1.y) < 360:
                    self._spawn_explosion(bullet.x, bullet.y, 1.25)
                    bullet.alive = False
                if bullet.owner_slot != 2 and distance_sq(bullet.x, bullet.y, self.player_2.x, self.player_2.y) < 360:
                    self._spawn_explosion(bullet.x, bullet.y, 1.25)
                    bullet.alive = False
            self.bullets = [b for b in self.bullets if b.alive]
            return
        for bullet in self.bullets:
            if bullet.owner_slot != 1 and distance_sq(bullet.x, bullet.y, self.player_1.x, self.player_1.y) < 360:
                self._spawn_explosion(bullet.x, bullet.y, 1.25)
                self.player_1.hp -= 1
                bullet.alive = False
            if bullet.owner_slot != 2 and distance_sq(bullet.x, bullet.y, self.player_2.x, self.player_2.y) < 360:
                self._spawn_explosion(bullet.x, bullet.y, 1.25)
                self.player_2.hp -= 1
                bullet.alive = False
        self.player_1.hp = max(0, self.player_1.hp)
        self.player_2.hp = max(0, self.player_2.hp)
        self.bullets = [b for b in self.bullets if b.alive]
        if self.player_1.hp <= 0:
            self._start_round_end(winner=2)
        elif self.player_2.hp <= 0:
            self._start_round_end(winner=1)

    def _start_round_end(self, winner: int) -> None:
        if self.round_over:
            return
        self.round_over = True
        self.round_restart_timer = ROUND_RESTART_DELAY_SEC
        self.bullets.clear()
        self.explosions.clear()
        if winner == 1:
            self.score_p1 += 1
            self.status = f"Раунд {self.round_number}: победил Игрок 1"
        else:
            self.score_p2 += 1
            self.status = f"Раунд {self.round_number}: победил Игрок 2"

    def _show_match_end_screen(self) -> None:
        self.match_over = True
        if self.mode == "online_client":
            my_score = self.score_p2
            enemy_score = self.score_p1
        else:
            my_score = self.score_p1
            enemy_score = self.score_p2
        title = "ПОБЕДА" if my_score > enemy_score else "ПОРАЖЕНИЕ"
        subtitle = f"Счет матча: {self.score_p1}:{self.score_p2}"
        if self.mode in {"online_host", "online_client"} and self.peer:
            self.window.show_view(
                OnlineMatchEndView(
                    title=title,
                    subtitle=subtitle,
                    level_name=self.level_name,
                    mode=self.mode,
                    peer=self.peer,
                    network_session_id=self.network_session_id,
                    network_my_slot=self.network_my_slot,
                )
            )
        else:
            self.window.show_view(MatchEndView(title, subtitle))

    def _advance_round_or_finish_match(self) -> None:
        match_finished = (
            self.round_number >= ROUND_COUNT
            or self.score_p1 >= ROUND_WIN_TARGET
            or self.score_p2 >= ROUND_WIN_TARGET
        )
        if match_finished:
            self.match_over = True
            if self.mode == "online_host" and self.peer:
                self._net_send_host()
            self._show_match_end_screen()
            return

        self.round_number += 1
        self.level.grid = [row[:] for row in self._initial_level_grid]
        self.level_renderer.mark_dirty()
        p1 = tile_to_xy(*self.level.spawn_1)
        p2 = tile_to_xy(*self.level.spawn_2)
        self.player_1.x, self.player_1.y = p1
        self.player_2.x, self.player_2.y = p2
        self.player_1.hp = 3
        self.player_2.hp = 3
        self.player_1.ammo = self.spawn_settings.initial_ammo
        self.player_2.ammo = self.spawn_settings.initial_ammo
        self.player_1.angle = 0
        self.player_2.angle = 0
        self.player_1.fire_cooldown = 0.0
        self.player_2.fire_cooldown = 0.0
        self.player_1.speed_boost_timer = 0.0
        self.player_2.speed_boost_timer = 0.0
        self.pickups.clear()
        self._pickup_spawn_timers = {
            "ammo": self.spawn_settings.ammo_spawn_interval_sec,
            "hp": self.spawn_settings.hp_spawn_interval_sec,
            "speed": self.spawn_settings.speed_spawn_interval_sec,
        }
        self._recalculate_visibility(force=True)
        self.round_over = False
        self.round_restart_timer = 0.0
        self.status = f"Раунд {self.round_number}: бой!"


def distance_sq(x1: float, y1: float, x2: float, y2: float) -> float:
    return (x1 - x2) ** 2 + (y1 - y2) ** 2


def draw_spawn_markers(level: ArenaLevel) -> None:
    spawn_1_x, spawn_1_y = tile_to_xy(*level.spawn_1)
    spawn_2_x, spawn_2_y = tile_to_xy(*level.spawn_2)
    arcade.draw_circle_outline(spawn_1_x, spawn_1_y, TILE_SIZE * 0.35, arcade.color.YELLOW, 2)
    arcade.draw_circle_outline(spawn_2_x, spawn_2_y, TILE_SIZE * 0.35, arcade.color.RED, 2)


def run() -> None:
    ensure_assets()
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, resizable=False, update_rate=1 / 60)
    window.show_view(MainMenuView())
    arcade.run()
