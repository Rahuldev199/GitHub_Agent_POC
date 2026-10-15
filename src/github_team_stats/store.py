"""Backward-compatible persistence adapter imports."""

from github_team_stats.application.ports import StatsStore
from github_team_stats.infrastructure.persistence import MongoStatsStore, SQLiteStatsStore

__all__ = ["MongoStatsStore", "SQLiteStatsStore", "StatsStore"]
