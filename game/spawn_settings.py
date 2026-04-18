from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PickupSpawnSettings:
    ammo_spawn_interval_sec: float = 8.0
    hp_spawn_interval_sec: float = 14.0
    speed_spawn_interval_sec: float = 12.0
    max_pickups_per_type: int = 2
    initial_ammo: int = 10
    ammo_bonus: int = 5
    max_hp: int = 5
    speed_boost_multiplier: float = 1.45
    speed_boost_duration_sec: float = 5.0
    min_pickup_distance_tiles: int = 6
    min_distance_from_tanks_tiles: int = 5


DEFAULT_PICKUP_SPAWN_SETTINGS = PickupSpawnSettings()
