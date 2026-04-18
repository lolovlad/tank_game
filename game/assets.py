from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

from .config import IMAGES_DIR


IMAGE_MAP = {
    "background": "Background_log.png",
    "tank_player": "yellow_tank.png",
    "tank_enemy": "gray_tank.png",
    "bullet": "bullet.png",
    "wall_breakable": "break_wall.png",
    "wall_metal": "metal_wall.png",
    "explosion": "взрыв.png",
    "icon": "Tanks_icon.png",
    "pickup_ammo": "pickup_ammo.png",
    "pickup_hp": "pickup_hp.png",
    "pickup_speed": "pickup_speed.png",
}

# Если файл с основным именем не найден, пробуем альтернативы (ручная подстановка в assets/images).
PICKUP_ICON_ALTERNATES: dict[str, tuple[str, ...]] = {
    "pickup_ammo": ("ammo.png", "bullets.png", "patron.png", "ammo_box.png"),
    "pickup_hp": ("hp.png", "heart.png", "medkit.png", "health.png"),
    "pickup_speed": ("speed.png", "boost.png", "lightning.png", "nitro.png"),
}

# Явно заданные файлы, которые пользователь добавил в сессию Cursor.
PICKUP_ICON_OVERRIDES: dict[str, str] = {
    "pickup_ammo": r"C:\Users\user\.cursor\projects\d-pythonProdgect-mario\assets\c__Users_user_AppData_Roaming_Cursor_User_workspaceStorage_03fb3477011fa98252b674698ece8499_images_ammor-7500759c-838a-4905-992b-c91ece1e4b80.png",
    "pickup_hp": r"C:\Users\user\.cursor\projects\d-pythonProdgect-mario\assets\c__Users_user_AppData_Roaming_Cursor_User_workspaceStorage_03fb3477011fa98252b674698ece8499_images_hart-0c3d7081-b056-409e-9958-53d76e19a082.png",
}

RAW_BASE = "https://raw.githubusercontent.com/lolovlad/clientTangGame/master/files/images"


def ensure_assets() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    for file_name in IMAGE_MAP.values():
        file_path = IMAGES_DIR / file_name
        if file_path.exists():
            continue
        url = f"{RAW_BASE}/{urllib.parse.quote(file_name)}"
        try:
            urllib.request.urlretrieve(url, file_path)
        except Exception:
            # Game can still run with fallback colors.
            continue


def get_asset_path(name: str) -> Path | None:
    file_name = IMAGE_MAP.get(name)
    if not file_name:
        return None
    path = IMAGES_DIR / file_name
    return path if path.exists() else None


def resolve_pickup_texture_path(kind: str) -> Path | None:
    """Путь к PNG иконки буста: сначала основное имя из IMAGE_MAP, затем альтернативы."""
    key = {"ammo": "pickup_ammo", "hp": "pickup_hp", "speed": "pickup_speed"}.get(kind)
    if not key:
        return None
    override_path = PICKUP_ICON_OVERRIDES.get(key)
    if override_path:
        p = Path(override_path)
        if p.exists():
            return p
    primary = IMAGE_MAP.get(key)
    candidates: list[str] = []
    if primary:
        candidates.append(primary)
    candidates.extend(PICKUP_ICON_ALTERNATES.get(key, ()))
    for name in candidates:
        path = IMAGES_DIR / name
        if path.exists():
            return path
    return None
