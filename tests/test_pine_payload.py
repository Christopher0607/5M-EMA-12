"""Parse the webhook JSON the Pine script actually emits, and validate it.

This exists because of a specific bug. An earlier build sent TradersPost a flat
`"stop": 21160.25`. That field is not in the spec, TradersPost ignores unknown
fields silently, and the result was a live position carrying no stop at all —
no error anywhere, on either side. Reading the Pine source did not catch it;
reconstructing the string and parsing it would have.

Pine's string concatenation is a subset of Python's — quoted literals joined by
`+` — so the payload lines can be lifted straight out of the source and
evaluated here. Only the ternary needs translating. That keeps this test honest:
it reads the shipped file rather than a copy of it that can drift.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "pine" / "nq_ema12_open.pine"

# Names whose right-hand side is pure string work and can be evaluated here.
PAYLOAD_NAMES = ("pmCreds", "tpLong", "tpShort", "tpFlat", "pmLong", "pmShort",
                 "pmFlat", "txLong", "txShort", "txFlat", "DISARM",
                 "liveLong", "liveShort", "longMsg", "shortMsg", "flatMsg")


# ----------------------------------------------------- Pine -> Python

def _protect(expr: str) -> tuple[str, list[str]]:
    """Swap string literals for placeholders so `:` inside them is not a ternary."""
    lits: list[str] = []

    def take(m: re.Match) -> str:
        lits.append(m.group(0))
        return f"\x00{len(lits) - 1}\x00"

    return re.sub(r"'[^']*'|\"[^\"]*\"", take, expr), lits


def _restore(expr: str, lits: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: lits[int(m.group(1))], expr)


def _ternary(expr: str) -> str:
    """`cond ? a : b` -> `(a if cond else b)`, right-associative, depth-aware."""
    depth = 0
    for i, c in enumerate(expr):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "?" and depth == 0:
            # matching ':' is the one closing THIS '?', skipping nested ones
            pending, j, d = 0, i + 1, 0
            while j < len(expr):
                ch = expr[j]
                if ch in "([":
                    d += 1
                elif ch in ")]":
                    d -= 1
                elif d == 0 and ch == "?":
                    pending += 1
                elif d == 0 and ch == ":":
                    if pending == 0:
                        break
                    pending -= 1
                j += 1
            cond, then, other = expr[:i], expr[i + 1:j], expr[j + 1:]
            return (f"({_ternary(then)} if {_ternary(cond)} "
                    f"else {_ternary(other)})")
    # no top-level ternary: recurse into bracketed groups
    return re.sub(r"\(([^()]*)\)", lambda m: "(" + _ternary(m.group(1)) + ")", expr)


def pine_to_python(expr: str) -> str:
    protected, lits = _protect(expr)
    return _restore(_ternary(protected), lits)


def evaluate(bridge: str, armed: bool, token: str = "", account: str = "",
             symbol: str = "MNQ", qty: str = "3",
             long_stop: str = "21160.25", short_stop: str = "21360.75") -> dict:
    """Evaluate the shipped script's payload assignments with concrete values."""
    ns: dict[str, object] = {
        "alertSym": symbol, "qtyStr": qty,
        "longStopStr": long_stop, "shortStopStr": short_stop,
        "pmtToken": token, "pmtAcct": account,
        "bridge": bridge, "armed": armed,
    }
    src = SCRIPT.read_text(encoding="utf-8").split("\n")
    seen = set()
    for raw in src:
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+?)\s*$", raw)
        if not m or m.group(1) not in PAYLOAD_NAMES:
            continue
        name, expr = m.group(1), m.group(2)
        ns[name] = eval(pine_to_python(expr), {"__builtins__": {}}, ns)
        seen.add(name)
    missing = set(PAYLOAD_NAMES) - seen
    assert not missing, f"payload assignments not found in the script: {missing}"
    return ns


# ----------------------------------------------------- translator sanity

def test_ternary_translation_handles_colon_inside_a_literal():
    got = pine_to_python("""x == "" ? "" : ',"token":"' + t + '"'""")
    assert eval(got, {}, {"x": "", "t": "T"}) == ""
    assert eval(got, {}, {"x": "a", "t": "T"}) == ',"token":"T"'


def test_ternary_translation_is_right_associative():
    got = pine_to_python('b == "A" ? "ra" : b == "B" ? "rb" : "rc"')
    assert eval(got, {}, {"b": "A"}) == "ra"
    assert eval(got, {}, {"b": "B"}) == "rb"
    assert eval(got, {}, {"b": "Z"}) == "rc"


# ----------------------------------------------------- TradersPost

def test_traderspost_entry_is_valid_json_with_a_nested_stop():
    ns = evaluate("TradersPost", armed=True)
    msg = json.loads(ns["longMsg"])
    assert msg["ticker"] == "MNQ"
    assert msg["action"] == "buy"
    assert msg["sentiment"] == "bullish"          # NOT "long"
    assert msg["quantity"] == 3
    assert msg["stopLoss"] == {"type": "stop", "stopPrice": 21160.25}


def test_traderspost_never_emits_a_flat_stop_field():
    """The regression. A flat `stop` is dropped silently and the position runs bare."""
    for m in ("longMsg", "shortMsg"):
        msg = json.loads(evaluate("TradersPost", armed=True)[m])
        assert "stop" not in msg, "flat `stop` is ignored by TradersPost"
        assert isinstance(msg["stopLoss"], dict)
        assert msg["stopLoss"]["stopPrice"] > 0


def test_traderspost_short_uses_bearish():
    msg = json.loads(evaluate("TradersPost", armed=True)["shortMsg"])
    assert (msg["action"], msg["sentiment"]) == ("sell", "bearish")
    assert msg["stopLoss"]["stopPrice"] == 21360.75


def test_traderspost_sentiments_are_all_in_the_spec_enum():
    ns = evaluate("TradersPost", armed=True)
    got = {json.loads(ns[m])["sentiment"] for m in ("longMsg", "shortMsg", "flatMsg")}
    assert got == {"bullish", "bearish", "flat"}


def test_traderspost_exit_is_valid_json():
    msg = json.loads(evaluate("TradersPost", armed=True)["flatMsg"])
    assert msg == {"ticker": "MNQ", "action": "exit", "sentiment": "flat"}


# ----------------------------------------------------- PickMyTrade

def test_pickmytrade_entry_is_valid_json():
    msg = json.loads(evaluate("PickMyTrade", armed=True)["longMsg"])
    assert msg["symbol"] == "MNQ"
    assert msg["data"] == "buy"
    assert msg["quantity"] == 3
    assert msg["sl"] == 21160.25


def test_pickmytrade_credentials_are_omitted_when_blank():
    msg = json.loads(evaluate("PickMyTrade", armed=True)["longMsg"])
    assert "token" not in msg and "account_id" not in msg


def test_pickmytrade_credentials_are_included_when_set():
    ns = evaluate("PickMyTrade", armed=True, token="tk123", account="acc9")
    for m in ("longMsg", "shortMsg", "flatMsg"):
        msg = json.loads(ns[m])
        assert msg["token"] == "tk123"
        assert msg["account_id"] == "acc9"


def test_pickmytrade_exit_uses_close():
    msg = json.loads(evaluate("PickMyTrade", armed=True)["flatMsg"])
    assert msg == {"symbol": "MNQ", "data": "close"}


def test_the_two_schemas_overlap_only_on_quantity():
    """Mixing them is the setup error the bridge selector exists to prevent.

    `quantity` is the one field both spell the same way. Everything that
    identifies the order - the instrument, the side, the stop - differs, so a
    payload sent to the wrong bridge is rejected rather than half-understood.
    """
    tp = set(json.loads(evaluate("TradersPost", armed=True)["longMsg"]))
    pm = set(json.loads(evaluate("PickMyTrade", armed=True)["longMsg"]))
    assert tp & pm == {"quantity"}
    for field in ("ticker", "action", "sentiment", "stopLoss"):
        assert field in tp and field not in pm
    for field in ("symbol", "data", "sl"):
        assert field in pm and field not in tp


# ----------------------------------------------------- safety behaviour

@pytest.mark.parametrize("bridge", ["TradersPost", "PickMyTrade", "Plain text"])
def test_disarmed_entries_are_not_parseable_as_an_order(bridge):
    ns = evaluate(bridge, armed=False)
    for m in ("longMsg", "shortMsg"):
        assert ns[m] == ns["DISARM"]
        with pytest.raises(json.JSONDecodeError):
            json.loads(ns[m])


@pytest.mark.parametrize("bridge", ["TradersPost", "PickMyTrade"])
def test_exit_stays_live_while_disarmed(bridge):
    """Disarming must never strand an open position: the flatten still has to work."""
    disarmed = evaluate(bridge, armed=False)
    armed = evaluate(bridge, armed=True)
    assert disarmed["flatMsg"] == armed["flatMsg"]
    json.loads(disarmed["flatMsg"])


def test_armed_defaults_to_off_in_the_shipped_script():
    src = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r'armed\s*=\s*input\.bool\(false,\s*"Arm live orders"', src)


def test_plain_text_bridge_emits_no_json():
    ns = evaluate("Plain text", armed=True)
    assert ns["longMsg"].startswith("LONG 3 MNQ")
    assert "21160.25" in ns["longMsg"]
    with pytest.raises(json.JSONDecodeError):
        json.loads(ns["longMsg"])
