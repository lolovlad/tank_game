from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import DEFAULT_LEVEL_NAME, GRID_COLS, GRID_ROWS, LEVELS_DIR

EMPTY = 0
BREAKABLE = 1
METAL = 2


@dataclass
class ArenaLevel:
    name: str
    rows: int
    cols: int
    grid: list[list[int]]
    spawn_1: tuple[int, int]
    spawn_2: tuple[int, int]

    @classmethod
    def empty(cls, name: str = DEFAULT_LEVEL_NAME) -> "ArenaLevel":
        grid = [[EMPTY for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]
        for row in range(GRID_ROWS):
            grid[row][0] = METAL
            grid[row][GRID_COLS - 1] = METAL
        for col in range(GRID_COLS):
            grid[0][col] = METAL
            grid[GRID_ROWS - 1][col] = METAL
        return cls(name=name, rows=GRID_ROWS, cols=GRID_COLS, grid=grid, spawn_1=(2, 2), spawn_2=(GRID_COLS - 3, GRID_ROWS - 3))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["spawn_1"] = list(self.spawn_1)
        payload["spawn_2"] = list(self.spawn_2)
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "ArenaLevel":
        return cls(
            name=payload["name"],
            rows=payload["rows"],
            cols=payload["cols"],
            grid=payload["grid"],
            spawn_1=tuple(payload["spawn_1"]),
            spawn_2=tuple(payload["spawn_2"]),
        )


def save_level(level: ArenaLevel) -> Path:
    LEVELS_DIR.mkdir(parents=True, exist_ok=True)
    path = LEVELS_DIR / f"{level.name}.json"
    with path.open("w", encoding="utf-8") as file:
        json.dump(level.to_dict(), file, ensure_ascii=False, indent=2)
    return path


def load_level(name: str) -> ArenaLevel:
    path = LEVELS_DIR / f"{name}.json"
    if not path.exists():
        return ArenaLevel.empty(name)
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return ArenaLevel.from_dict(payload)


def level_names() -> list[str]:
    if not LEVELS_DIR.exists():
        return [DEFAULT_LEVEL_NAME]
    names = sorted(item.stem for item in LEVELS_DIR.glob("*.json"))
    return names or [DEFAULT_LEVEL_NAME]


def level_display_name(name: str) -> str:
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in cleaned.split()) or "Без названия"


def next_custom_level_name(prefix: str = "custom_arena") -> str:
    existing = set(level_names())
    if prefix not in existing:
        return prefix
    idx = 2
    while f"{prefix}_{idx}" in existing:
        idx += 1
    return f"{prefix}_{idx}"


def generate_random_level(name: str, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> ArenaLevel:
    rows = max(12, rows)
    cols = max(16, cols)
    spawn_1 = (2, 2)
    spawn_2 = (cols - 3, rows - 3)
    retries = 24
    for _ in range(retries):
        grid = [[EMPTY for _ in range(cols)] for _ in range(rows)]
        for row in range(rows):
            grid[row][0] = METAL
            grid[row][cols - 1] = METAL
        for col in range(cols):
            grid[0][col] = METAL
            grid[rows - 1][col] = METAL

        safe_tiles = {
            spawn_1,
            spawn_2,
            (spawn_1[0] + 1, spawn_1[1]),
            (spawn_1[0], spawn_1[1] + 1),
            (spawn_2[0] - 1, spawn_2[1]),
            (spawn_2[0], spawn_2[1] - 1),
        }
        for row in range(1, rows - 1):
            for col in range(1, cols - 1):
                if (col, row) in safe_tiles:
                    continue
                roll = random.random()
                if roll < 0.10:
                    grid[row][col] = METAL
                elif roll < 0.32:
                    grid[row][col] = BREAKABLE

        if _has_path(grid, spawn_1, spawn_2):
            return ArenaLevel(name=name, rows=rows, cols=cols, grid=grid, spawn_1=spawn_1, spawn_2=spawn_2)

    return ArenaLevel.empty(name)


def _has_path(grid: list[list[int]], start: tuple[int, int], goal: tuple[int, int]) -> bool:
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    stack = [start]
    visited: set[tuple[int, int]] = set()
    while stack:
        col, row = stack.pop()
        if (col, row) in visited:
            continue
        visited.add((col, row))
        if (col, row) == goal:
            return True
        for n_col, n_row in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
            if not (0 <= n_col < cols and 0 <= n_row < rows):
                continue
            if grid[n_row][n_col] != EMPTY:
                continue
            if (n_col, n_row) not in visited:
                stack.append((n_col, n_row))
    return False
