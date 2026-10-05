"""Server time <-> UTC <-> America/New_York.

"Server time" is the broker wall clock held as a naive datetime (the MT5 API labels it as UTC epoch).
A ServerClock is a list of eras (start instant in UTC, rule); every rule is a function of the UTC instant:

    ("fixed", h)   server = UTC + h
    ("ny", k)      server = New York wall clock + k hours      (k=7 is the classic "NY close" clock:
                   UTC+2 in US winter / UTC+3 in US summer, so 09:30 ET is always 16:30 server)
    ("eu", w)      server = UTC + w, plus 1 hour while EU summer time is active   (w=2: EET, w=0: London)

Server -> UTC edge cases (only ever hit on Sunday mornings when the market is shut):
    ambiguous server time (clock repeats at fall-back)  -> first occurrence (earlier UTC)
    nonexistent server time (clock skips at spring-forward) -> read with the pre-transition (larger) offset
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ET = "America/New_York"
HOUR = pd.Timedelta(hours=1)


def _wall_offset(utc: pd.DatetimeIndex, zone: str) -> np.ndarray:
    """Hours between `zone` wall clock and UTC at each UTC instant."""
    local = utc.tz_localize("UTC").tz_convert(zone).tz_localize(None)
    return ((local - utc) / HOUR).to_numpy()


def _rule_offset(utc: pd.DatetimeIndex, kind: str, p: float) -> np.ndarray:
    if kind == "fixed":
        return np.full(len(utc), float(p))
    if kind == "ny":
        return p + _wall_offset(utc, ET)
    if kind == "eu":
        return p + _wall_offset(utc, "Europe/London")     # London offset = 0/+1 = EU summer-time flag
    raise ValueError(kind)


def _rule_candidates(kind: str, p: float) -> list[float]:
    return {"fixed": [p], "ny": [p - 5, p - 4], "eu": [p, p + 1]}[kind]


class ServerClock:
    def __init__(self, eras):
        """eras: [(start_utc, kind, param), ...]; the first era applies to everything before the second."""
        eras = sorted(((pd.Timestamp(s), k, float(p)) for s, k, p in eras), key=lambda e: e[0])
        self.eras = eras
        self._starts = np.array([e[0].value for e in eras], dtype="int64")

    # -- offsets ---------------------------------------------------------
    def offset_hours(self, utc) -> np.ndarray:
        """server - UTC in hours at each (naive UTC) instant."""
        utc = pd.DatetimeIndex(utc).as_unit("ns")
        era = np.clip(np.searchsorted(self._starts, utc.asi8, side="right") - 1, 0, len(self.eras) - 1)
        out = np.empty(len(utc))
        for i, (_, kind, p) in enumerate(self.eras):
            sel = era == i
            if sel.any():
                out[sel] = _rule_offset(utc[sel], kind, p)
        return out

    def _candidates(self) -> list[float]:
        return sorted({c for _, k, p in self.eras for c in _rule_candidates(k, p)}, reverse=True)

    # -- conversions -----------------------------------------------------
    def to_utc(self, server) -> pd.DatetimeIndex:
        server = pd.DatetimeIndex(server).as_unit("ns")
        out = np.full(len(server), np.iinfo("int64").min, dtype="int64")
        done = np.zeros(len(server), dtype=bool)
        cands = self._candidates()
        for c in cands:                                   # largest offset first -> earliest UTC first
            u = server - c * HOUR
            ok = (self.offset_hours(u) == c) & ~done
            out[ok] = u.asi8[ok]
            done |= ok
        if not done.all():                                # nonexistent clock time
            out[~done] = (server[~done] - cands[0] * HOUR).asi8
        return pd.DatetimeIndex(out.view("datetime64[ns]"))

    def to_et(self, server) -> pd.DatetimeIndex:
        """Naive New York wall clock."""
        return self.to_utc(server).tz_localize("UTC").tz_convert(ET).tz_localize(None)

    def utc_to_server(self, utc) -> pd.DatetimeIndex:
        utc = pd.DatetimeIndex(utc).as_unit("ns")
        return utc + pd.to_timedelta(self.offset_hours(utc), unit="h")

    def et_to_server(self, et) -> pd.DatetimeIndex:
        utc = pd.DatetimeIndex(et).as_unit("ns").tz_localize(ET, ambiguous=False, nonexistent="shift_forward").tz_convert("UTC").tz_localize(None)
        return self.utc_to_server(utc)

    # -- persistence -----------------------------------------------------
    def to_json(self) -> list[dict]:
        return [{"start_utc": str(s), "kind": k, "param": p} for s, k, p in self.eras]

    @classmethod
    def from_json(cls, items):
        return cls([(i["start_utc"], i["kind"], i["param"]) for i in items])

    def save(self, path: Path, extra: dict | None = None):
        Path(path).write_text(json.dumps({"eras": self.to_json(), **(extra or {})}, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path):
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8"))["eras"])


NY_CLOSE = ServerClock([("1900-01-01", "ny", 7)])     # reference convention the user asked us to test
