# app/calculation_formula.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class PeriodInputs:
    # Main meters
    E: Optional[float]          # GRID export
    E_LMV: Optional[float]      # INTERCONNECT import
    E_self: Optional[float]     # SELF import

    # RTS & BESS sources (length = 4, missing = None)
    RTS_exports: Optional[float]
    BESS_charge: Optional[float]
    BESS_discharge: Optional[float]


@dataclass
class PeriodResult:
    K: float
    RTS_to_LMV: float
    BESS_to_LMV: float


def calc_K(E: Optional[float], E_LMV: Optional[float], last_K: float) -> float:
    if E is not None and E_LMV is not None and E > 0 and E_LMV > 0:
        return max(0.0, ((E - E_LMV) / E))
    return last_K


def sum_present(values):
    return sum(v for v in values if v is not None)


def apply_formula(
    *,
    formula_code: str,
    inputs: PeriodInputs,
    last_K: float,
) -> PeriodResult:
    """
    Applies EXACT settlement formulas (a–g).
    """

    E = inputs.E or 0.0
    E_LMV = inputs.E_LMV or 0.0
    E_self = inputs.E_self or 0.0

    E_RTS = inputs.RTS_exports or 0.0
    E_BESS_charge = inputs.BESS_charge or 0.0
    E_NORMAL_BESS_DIS = inputs.BESS_discharge or 0.0

    # K handling
    K = calc_K(E, E_LMV, last_K)

    RTS_to_LMV = 0.0
    BESS_to_LMV = 0.0

    # ---------------- FORMULAS ----------------

    print("Total Grid: ", E, ", Total interconnect", E_LMV, ", Self: ", E_self," RTS: ", E_RTS, ", BESS Charge: ", E_BESS_charge, ", E normal Bess Dis: ", E_NORMAL_BESS_DIS,", K: ", K, "Formula code: ", formula_code)
    if formula_code == "F01_NORMAL":
        RTS_to_LMV = (E_RTS - E_BESS_charge - E_self) * (1 - K)
        BESS_to_LMV = E * (1 - K) - RTS_to_LMV

    elif formula_code == "F02_NO_GRID":
        RTS_to_LMV = (E_RTS - E_BESS_charge - E_self) * (1 - K)
        BESS_to_LMV = E_LMV - RTS_to_LMV

    elif formula_code == "F03_NO_INTERCONNECT":
        RTS_to_LMV = (E_RTS - E_BESS_charge - E_self) * (1 - K)
        BESS_to_LMV = E * (1 - K) - RTS_to_LMV

    elif formula_code == "F04_ONLY_RTS_FAULTY":
        RTS_to_LMV = (E - E_NORMAL_BESS_DIS) * (1 - K)
        BESS_to_LMV = E_NORMAL_BESS_DIS * (1 - K)

    elif formula_code == "F05_NO_SELF":
        RTS_to_LMV = (E - E_NORMAL_BESS_DIS) * (1 - K)
        BESS_to_LMV = E_NORMAL_BESS_DIS * (1 - K)

    elif formula_code == "F06_ONLY_BESS_FAULTY":
        RTS_to_LMV = (E - E_NORMAL_BESS_DIS) * (1 - K)
        BESS_to_LMV = E_NORMAL_BESS_DIS * (1 - K)

    elif formula_code == "F07_BOTH_BESS_RTS_FAULTY":
        RTS_to_LMV = (E - E_NORMAL_BESS_DIS) * (1 - K)
        BESS_to_LMV = E_NORMAL_BESS_DIS * (1 - K)

    else:
        # F99_INVALID or unknown
        RTS_to_LMV = 0.0
        BESS_to_LMV = 0.0

    # Safety clamp
    RTS_to_LMV = max(0.0, RTS_to_LMV)
    BESS_to_LMV = max(0.0, BESS_to_LMV)

    return PeriodResult(
        K=K,
        RTS_to_LMV=RTS_to_LMV,
        BESS_to_LMV=BESS_to_LMV,
    )
