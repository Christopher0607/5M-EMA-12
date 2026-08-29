"""The funded phase and the full prop-firm career loop.

Passing an evaluation is not the goal — getting paid is. `src/propfirm.py` stops
at pass/bust; this module continues into the funded account, where the money
actually moves: qualifying days, a safety net, consistency rules, payout caps,
profit splits, and the fee stack that runs the whole time.

A career is the whole journey, not one account:

    buy evaluation -> pass -> funded -> payouts -> bust -> buy evaluation -> ...

run across the entire history. That is what "how did this do at a prop firm"
means for someone who resets and tries again, which is what people actually do.

One consequence worth stating because it is easy to net out by accident: taking
a payout *lowers the balance* while the trailing threshold is already locked, so
every withdrawal genuinely increases the chance the account busts later. That is
modelled here rather than settled up at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.propfirm import run_account


@dataclass
class Payout:
    day: int            # index into the days frame
    gross: float        # withdrawn from the account
    net: float          # after the profit split
    balance_after: float
    capped: bool = False   # the firm's cap, not the balance, limited this one


@dataclass
class Career:
    evals_bought: int = 0
    evals_passed: int = 0
    funded_accounts: int = 0
    payouts: list = field(default_factory=list)
    fees_paid: float = 0.0
    days_in_eval: int = 0
    days_funded: int = 0
    ended: str = "end_of_data"

    @property
    def withdrawn(self) -> float:
        return sum(p.net for p in self.payouts)

    @property
    def net_to_trader(self) -> float:
        return self.withdrawn - self.fees_paid


def _split(gross: float, taken_so_far: float, full_to: float, after: float) -> float:
    """Apply the firm's profit split to one withdrawal."""
    full_room = max(full_to - taken_so_far, 0.0)
    at_full = min(gross, full_room)
    return at_full + (gross - at_full) * after


def _payout_size(excess: float, policy: dict) -> float:
    kind = policy["kind"]
    if kind == "all":
        return excess
    if kind == "fraction":
        return excess * float(policy["value"])
    if kind == "threshold":
        return excess if excess >= float(policy["value"]) else 0.0
    raise ValueError(f"unknown withdrawal policy {kind!r}")


def run_funded(days: pd.DataFrame, rules: dict, policy: dict, monthly_fee: float,
               start_idx: int, max_days: int = 10_000) -> dict:
    """Trade a funded account until it busts or the data runs out.

    Threshold mechanics mirror `propfirm.run_account`: the intraday trough is
    tested against the level in force when the day opened, and the trailing
    threshold is dragged by the intraday high (Apex) or the closing balance
    (TopStep).
    """
    balance = float(rules["balance"])
    trail = float(rules["trailing_dd"])
    dll = rules.get("daily_loss_limit")
    intraday = rules.get("trail_basis", "intraday") == "intraday"
    lock_at = (balance + (100.0 if intraday else 0.0)
               if rules.get("lock_at_initial") else np.inf)
    # Lucid converts the trailing threshold to a STATIC floor at the starting
    # balance once you are funded - it stops following equity upward entirely.
    # That is the single friendliest rule in this comparison and it changes the
    # withdrawal calculus: money taken out no longer drags a ratchet down onto you.
    static_floor = bool(rules.get("static_floor", False))
    dll_soft = bool(rules.get("daily_loss_soft", False))
    safety = float(rules["safety_net"])
    min_days = int(rules["min_trading_days"])
    min_day = float(rules["min_day_profit"])
    cap = rules.get("payout_cap")
    # Apex caps only the first few withdrawals; TopStep caps every Standard-path
    # payout. `capped_payouts: null` means "always", not "never".
    capped_raw = rules.get("capped_payouts", 0)
    capped_always = cap is not None and capped_raw is None
    capped_n = 0 if capped_raw is None else int(capped_raw)
    consistency = rules.get("consistency_max_day_share")
    full_to = float(rules.get("split_full_to") or 0.0)
    after = float(rules.get("split_after") if rules.get("split_after") is not None else 1.0)

    threshold = balance - trail
    peak = balance
    qualifying = 0
    profit_days: list[float] = []      # winning days since the last payout
    lifetime_days: list[float] = []    # every winning day, for lifetime-basis rules
    # TPT measures its consistency rule against *lifetime* profit, so a payout
    # does not reset it; Apex and Lucid measure it per payout cycle.
    lifetime_basis = bool(rules.get("consistency_lifetime", False))
    payouts: list[Payout] = []
    taken = 0.0
    fees = 0.0

    window = days.iloc[start_idx:start_idx + max_days]
    for n, row in enumerate(window.itertuples(index=False), start=1):
        incoming = threshold
        day_low = balance - row.down
        day_close = balance + row.pnl

        if n % 21 == 1:                 # roughly one calendar month of sessions
            fees += monthly_fee

        if day_low <= incoming:
            return _funded_result("blown", n, balance, payouts, fees, "trailing_drawdown")
        if dll is not None and row.pnl <= -dll and not dll_soft:
            return _funded_result("blown", n, day_close, payouts, fees, "daily_loss_limit")

        if not static_floor:
            peak = max(peak, balance + row.up if intraday else day_close)
            threshold = max(threshold, min(peak - trail, lock_at))
        if day_close <= threshold:
            return _funded_result("blown", n, day_close, payouts, fees, "trailing_drawdown")

        balance = day_close
        if row.pnl >= min_day:
            qualifying += 1
        if row.pnl > 0:
            profit_days.append(row.pnl)
            lifetime_days.append(row.pnl)

        # ---- payout attempt -------------------------------------------------
        if qualifying < min_days:
            continue
        excess = balance - safety
        if excess <= 0:
            continue
        if consistency is not None:
            pool = lifetime_days if lifetime_basis else profit_days
            total = sum(pool)
            if pool and total > 0 and max(pool) / total > float(consistency):
                continue        # one lumpy day blocks the payout until it dilutes
        gross = _payout_size(excess, policy)
        hit_cap = False
        if cap is not None and (capped_always or len(payouts) < capped_n):
            if gross > float(cap):
                hit_cap = True
            gross = min(gross, float(cap))
        if gross <= 0:
            continue

        balance -= gross
        net = _split(gross, taken, full_to, after)
        taken += gross
        payouts.append(Payout(day=start_idx + n, gross=gross, net=net,
                              balance_after=balance, capped=hit_cap))
        qualifying = 0
        profit_days = []

    return _funded_result("survived", len(window), balance, payouts, fees, "end_of_data")


def _funded_result(outcome, days, balance, payouts, fees, reason) -> dict:
    return {"outcome": outcome, "days": days, "balance": balance,
            "payouts": payouts, "fees": fees, "reason": reason}


def run_career(days: pd.DataFrame, eval_rules: dict, funded_rules: dict,
               policy: dict, fees: dict, start_idx: int = 0,
               eval_cap: int = 250) -> Career:
    """Buy evaluations and trade funded accounts until the data runs out."""
    car = Career()
    cursor = start_idx
    n = len(days)
    while cursor < n:
        car.evals_bought += 1
        car.fees_paid += float(fees["evaluation"])
        res = run_account(days, eval_rules, start_idx=cursor, max_days=eval_cap)
        cursor += res["days"]
        car.days_in_eval += res["days"]
        if res["outcome"] != "passed":
            if res["outcome"] == "undecided" and cursor >= n:
                car.ended = "end_of_data"
            continue

        car.evals_passed += 1
        car.fees_paid += float(fees.get("activation", 0.0))
        fund = run_funded(days, funded_rules, policy,
                          float(fees.get("monthly_funded", 0.0)), start_idx=cursor)
        cursor += fund["days"]
        car.days_funded += fund["days"]
        car.funded_accounts += 1
        car.payouts.extend(fund["payouts"])
        car.fees_paid += fund["fees"]
    return car


def summarise_career(car: Career, days_total: int) -> dict:
    nets = [p.net for p in car.payouts]
    return {
        "evals_bought": car.evals_bought,
        "evals_passed": car.evals_passed,
        "funded_accounts": car.funded_accounts,
        "payouts": len(car.payouts),
        "withdrawn": car.withdrawn,
        "fees_paid": car.fees_paid,
        "net_to_trader": car.net_to_trader,
        "avg_payout": float(np.mean(nets)) if nets else 0.0,
        "largest_payout": float(max(nets)) if nets else 0.0,
        "first_payout_day": car.payouts[0].day if car.payouts else None,
        "capped_payouts": sum(1 for p in car.payouts if p.capped),
        "capped_pct": (100.0 * sum(1 for p in car.payouts if p.capped) / len(car.payouts)
                       if car.payouts else 0.0),
        "pct_time_funded": 100.0 * car.days_funded / max(days_total, 1),
        "days_funded": car.days_funded,
        "days_in_eval": car.days_in_eval,
    }


def career_distribution(days: pd.DataFrame, eval_rules: dict, funded_rules: dict,
                        policy: dict, fees: dict, step: int = 21,
                        horizon: int = 504) -> pd.DataFrame:
    """Start a career on every `step`-th session and run it for `horizon` sessions.

    One career from one start date is a single path. Restarting across the whole
    history gives the spread of outcomes a trader actually faces — the same
    reasoning as the rolling evaluation, carried through to payouts.
    """
    rows = []
    for i in range(0, max(len(days) - horizon, 1), step):
        sub = days.iloc[i:i + horizon].reset_index(drop=True)
        car = run_career(sub, eval_rules, funded_rules, policy, fees)
        rec = summarise_career(car, len(sub))
        rec["start_date"] = days.iloc[i]["session_date"]
        rows.append(rec)
    return pd.DataFrame(rows)


def risk_for(tier: dict, basis: dict) -> float:
    """Per-trade dollar risk for an account tier under one risk basis.

    This choice, not the account size, decides whether a bigger account helps.
    A tier's MLL scales 2.25x from $50K to $150K while a 1%-of-balance risk
    scales 3x, so under `pct_balance` the large account tolerates *fewer* full
    losses than the small one.
    """
    kind = basis["kind"]
    if kind == "fixed":
        return float(basis["value"])
    if kind == "pct_balance":
        return float(tier["balance"]) * float(basis["value"])
    if kind == "pct_mll":
        return float(tier["trailing_dd"]) * float(basis["value"])
    raise ValueError(f"unknown risk basis {kind!r}")


def losses_to_bust(tier: dict, basis: dict) -> float:
    """How many full stop-outs the tier absorbs before the loss limit is hit."""
    return float(tier["trailing_dd"]) / risk_for(tier, basis)


def scale_accounts(car: Career, n: int, legacy_split_full_to: float = 0.0,
                   split_after: float = 0.9) -> dict:
    """N identical funded accounts driven from one signal by a copier.

    They are perfectly correlated: same trades, same equity path, same bust day.
    Everything therefore multiplies exactly - payouts, withdrawals and fees alike
    - and **there is no diversification at all**; N accounts do not survive any
    longer than one, they just lose N times as much when they go.

    Two things genuinely do not scale linearly:

    * The payout cap is per account, so N accounts lift the income ceiling
      N-fold. This is the only real reason to add accounts, and it only pays off
      where the cap is actually binding.
    * The legacy 100%-of-first-$10k split threshold is tracked per *trader*, so
      it is claimed once across all accounts rather than once each. Under the
      flat 90/10 that applies to traders joining after 2026-01-12 it is moot.
    """
    gross = sum(p.gross for p in car.payouts) * n
    if legacy_split_full_to > 0:
        at_full = min(gross, legacy_split_full_to)
        net = at_full + (gross - at_full) * split_after
    else:
        net = sum(p.net for p in car.payouts) * n
    fees = car.fees_paid * n
    return {
        "accounts": n,
        "payouts": len(car.payouts) * n,
        "withdrawn_gross": gross,
        "withdrawn": net,
        "fees_paid": fees,
        "net_to_trader": net - fees,
        "capped_payouts": sum(1 for p in car.payouts if p.capped) * n,
    }


def funded_distribution(days: pd.DataFrame, rules: dict, policy: dict,
                        monthly_fee: float, step: int = 21,
                        horizon: int = 504) -> pd.DataFrame:
    """Fund an account on every `step`-th session and run it for `horizon` days.

    Running a single funded account from the first day of history answers the
    wrong question: it reports how the strategy did in 2010, not how a funded
    account behaves. Restarting across the whole period separates the funded
    phase's economics from the evaluation's difficulty and from the era the
    account happened to start in.
    """
    rows = []
    for i in range(0, max(len(days) - horizon, 1), step):
        sub = days.iloc[i:i + horizon].reset_index(drop=True)
        r = run_funded(sub, rules, policy, monthly_fee, 0)
        rows.append({
            "start_date": days.iloc[i]["session_date"],
            "payouts": len(r["payouts"]),
            "net": sum(p.net for p in r["payouts"]) - r["fees"],
            "survived": r["outcome"] == "survived",
            "days": r["days"],
        })
    return pd.DataFrame(rows)
