from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
LEVELS_DIR = ROOT_DIR / "levels"

SCREEN_WIDTH = 1720
SCREEN_HEIGHT = 920
SCREEN_TITLE = "Arcade Tank Arena"

GRID_COLS = 48
GRID_ROWS = 27
TILE_SIZE = 30

DEFAULT_LEVEL_NAME = "classic_arena"

SERVER_PORT = 57991
