# app/scenario.py

def detect_scenario(
    *,
    bess_missing_count: int,
    rfs_missing_count: int,
    self_available: bool,
    grid_available: bool,
    inter_available: bool,
) -> str:
    """
    Returns a descriptive scenario_code for grouping periods.
    This is NOT the settlement formula.
    """

    if not grid_available:
        return "NO_GRID"
    if not inter_available:
        return "NO_INTERCONNECT"
    if not self_available:
        return "NO_SELF"

    bess_faulty = bess_missing_count > 0
    rfs_faulty = rfs_missing_count > 0

    if bess_faulty and rfs_faulty:
        return "BESS_RTS_FAULTY"
    if bess_faulty:
        return "BESS_FAULTY"
    if rfs_faulty:
        return "RTS_FAULTY"

    return "ALL_OK"


def formula_for_interval_state(
    *,
    bess_missing_count: int,
    rfs_missing_count: int,
    self_available: bool,
    grid_available: bool,
    inter_available: bool,
) -> str:
    """
    Returns FINAL formula_code, aligned EXACTLY with the contract table.
    """

    # Self meter has priority
    if not self_available:
        return "F05_NO_SELF"

    bess_faulty = bess_missing_count > 0
    rfs_faulty = rfs_missing_count > 0

    if bess_faulty and rfs_faulty:
        return "F07_BOTH_BESS_RTS_FAULTY"
    if bess_faulty:
        return "F06_ONLY_BESS_FAULTY"
    if rfs_faulty:
        return "F04_ONLY_RTS_FAULTY"

    # Grid / interconnect only affect K (reuse last_K)
    if not grid_available:
        return "F02_NO_GRID"
    if not inter_available:
        return "F03_NO_INTERCONNECT"

    return "F01_NORMAL"
