"""Small inference helpers for batch 2 (PLAN section 9), numpy only so there is no dependency on statsmodels.

nw_ols: y = alpha + beta x by OLS with Newey-West (Bartlett kernel) standard errors and no small-sample correction, which is
what statsmodels' cov_type="HAC" (use_correction=False) computes. welch: Welch's unequal-variance t statistic and its df.
"""
import numpy as np


def nw_ols(y, x, lags: int = 5) -> dict:
    """OLS of y on [1, x] with Newey-West standard errors (Bartlett weights 1 - j / (lags + 1), j = 1..lags)."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    X = np.column_stack([np.ones(len(y)), x])
    nan = {"alpha": np.nan, "beta": np.nan, "se_alpha": np.nan, "se_beta": np.nan, "alpha_t": np.nan, "beta_t": np.nan}
    if len(y) <= lags + 2 or not np.isfinite(y).all() or not np.isfinite(x).all():
        return nan
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:                                      # x constant: no regression
        return nan
    coef = xtx_inv @ X.T @ y
    g = X * (y - X @ coef)[:, None]                                    # score contributions x_t * u_t
    s = g.T @ g
    for j in range(1, lags + 1):
        gj = g[j:].T @ g[:-j]
        s += (1 - j / (lags + 1)) * (gj + gj.T)
    se = np.sqrt(np.diag(xtx_inv @ s @ xtx_inv))
    return {"alpha": coef[0], "beta": coef[1], "se_alpha": se[0], "se_beta": se[1],
            "alpha_t": coef[0] / se[0] if se[0] > 0 else np.nan, "beta_t": coef[1] / se[1] if se[1] > 0 else np.nan}


def welch(a, b) -> dict:
    """mean(a) - mean(b), Welch t and Welch-Satterthwaite df for two independent samples."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    out = {"n_a": len(a), "n_b": len(b), "mean_a": np.nan, "mean_b": np.nan, "diff": np.nan, "t": np.nan, "df": np.nan}
    if len(a) < 2 or len(b) < 2:
        return out
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    out.update(mean_a=a.mean(), mean_b=b.mean(), diff=a.mean() - b.mean())
    if va + vb > 0:
        out.update(t=out["diff"] / np.sqrt(va + vb), df=(va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)))
    return out
