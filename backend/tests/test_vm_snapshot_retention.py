"""Test selezione pruning retention vm_snapshot."""

from services.vm_snapshot.retention import select_prunable

SNAPSHOTS = [
    {"name": "autodaily_20260718_030000", "snaptime": 1784500000},
    {"name": "autodaily_20260719_030000", "snaptime": 1784586400},
    {"name": "autodaily_20260720_030000", "snaptime": 1784672800},
    {"name": "autodaily_20260721_030000", "snaptime": 1784759200},
    {"name": "autohourly_20260721_120000", "snaptime": 1784791600},  # altro label
    {"name": "autosnap_2026-07-21_03:00:00_daily"},                   # Sanoid
    {"name": "pre-upgrade", "description": "manuale"},                # manuale
    {"name": "autodaily_20260750_030000"},                            # malformato (giorno 50)
]


def test_prunes_only_own_label_beyond_keep():
    prunable = select_prunable(SNAPSHOTS, "daily", 2)
    assert prunable == ["autodaily_20260719_030000", "autodaily_20260718_030000"]


def test_keep_covers_all_returns_empty():
    assert select_prunable(SNAPSHOTS, "daily", 10) == []


def test_other_label_untouched():
    assert select_prunable(SNAPSHOTS, "hourly", 1) == []


def test_manual_and_sanoid_and_malformed_never_pruned():
    prunable = select_prunable(SNAPSHOTS, "daily", 1)
    assert "pre-upgrade" not in prunable
    assert "autosnap_2026-07-21_03:00:00_daily" not in prunable
    assert "autodaily_20260750_030000" not in prunable
    assert len(prunable) == 3


def test_keep_minimum_one():
    prunable = select_prunable(SNAPSHOTS, "daily", 0)
    assert "autodaily_20260721_030000" not in prunable  # il più recente resta sempre


def test_empty_input():
    assert select_prunable([], "daily", 3) == []
    assert select_prunable(None, "daily", 3) == []
