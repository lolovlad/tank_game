"""Экраны меню и вспомогательные UI-представления."""

from __future__ import annotations

from .arena_select import ArenaSelectView
from .base import BaseUI
from .lobby import ClientConnectView, HostWaitingView, LobbyView
from .main_menu import MainMenuView
from .match_end import MatchEndView, OnlineMatchEndView
from .mode_select import ModeSelectView
from .rules_help import RulesHelpView
from .settings_view import SettingsView

__all__ = [
    "ArenaSelectView",
    "BaseUI",
    "ClientConnectView",
    "HostWaitingView",
    "LobbyView",
    "MainMenuView",
    "MatchEndView",
    "ModeSelectView",
    "OnlineMatchEndView",
    "RulesHelpView",
    "SettingsView",
]
