"""Forward paper-tracker for the frozen H6a and H3a variants (spec: research/PLAN.md section 10). Paper only: nothing is ever traded."""
import pandas as pd

FORWARD_START = pd.Timestamp("2026-10-06")     # first New York trading day whose entries may be scored (PLAN section 10)
SYMBOL = "USTEC."                              # the audited instrument (PLAN section 1)
