"""Загрузка и кеш текстур по имени ассета."""

from __future__ import annotations

from pathlib import Path

import arcade

from .assets import get_asset_path, resolve_pickup_texture_path

TEXTURE_CACHE: dict[str, arcade.Texture] = {}


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
