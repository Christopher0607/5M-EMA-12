"""Regression tests for the Pine linter, anchored to a script TradingView accepts.

`tests/fixtures/known_good.pine` compiles in TradingView and produces trades.
That makes it ground truth, and it is the only evidence here stronger than
inspection: an earlier version of this linter reported three ERRORs on it, which
sent a real debugging session chasing a defect that did not exist. Any rule that
fires on this file is wrong, by definition.

The negative cases matter just as much. A linter that flags nothing is as
useless as one that flags working code, so each rule is also shown firing on the
shape it exists to catch.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lint_pine import RULES, bracket_depths, lint

FIXTURE = Path(__file__).parent / "fixtures" / "known_good.pine"
SHIPPED = ROOT / "pine" / "nq_ema12_open.pine"


# ------------------------------------------------------------ ground truth

def test_known_good_script_is_clean():
    """The fixture compiles in TradingView; every finding on it is a false positive."""
    found = lint(str(FIXTURE))
    assert found == [], "\n".join(f"line {f.line} [{f.rule}] {f.text}" for f in found)


def test_shipped_script_is_clean():
    found = lint(str(SHIPPED))
    assert found == [], "\n".join(f"line {f.line} [{f.rule}] {f.text}" for f in found)


def test_ternary_as_positional_argument_is_accepted():
    """Line 169 of the fixture. A deleted rule called this CE10015; Pine compiles it."""
    src = ["bgcolor(showZone and inTrade ? color.new(dirState == 1 ? #2a78d6 "
           ": #eb6834, 94) : na)"]
    assert [f for rule in RULES for f in rule(src)] == []


# -------------------------------------------------- continuation-indent rule

def test_continuation_inside_brackets_is_not_flagged(tmp_path):
    """Line 117 of the fixture: inside an unclosed `(` the indent cannot mislead."""
    p = tmp_path / "a.pine"
    p.write_text("stopDist = math.max(math.round(raw / tick) * tick,\n"
                 "                    tick)\n", encoding="utf-8")
    assert lint(str(p)) == []


def test_continuation_at_depth_zero_is_flagged(tmp_path):
    """The defect this rule exists for: a depth-0 break indented by a multiple of 4."""
    p = tmp_path / "b.pine"
    p.write_text("x = foo(a) +\n"
                 "    bar(b)\n", encoding="utf-8")
    found = lint(str(p))
    assert [f.rule for f in found] == ["continuation-indent"]
    assert found[0].line == 1


def test_multiline_string_concat_in_switch_is_flagged(tmp_path):
    """The actual root cause of the CE10015/CE10156 cascade, reproduced."""
    p = tmp_path / "c.pine"
    p.write_text('msg = switch bridge\n'
                 '    "TradersPost" =>\n'
                 '        \'{"a":"\' + sym + \'",\' +\n'
                 '        \'"b":"c"}\'\n', encoding="utf-8")
    found = lint(str(p))
    assert [f.rule for f in found] == ["continuation-indent"]
    assert found[0].line == 3


def test_switch_branch_arrow_is_not_a_continuation(tmp_path):
    p = tmp_path / "d.pine"
    p.write_text('msg = switch bridge\n'
                 '    "TradersPost" =>\n'
                 '        buildPost()\n', encoding="utf-8")
    assert lint(str(p)) == []


# ------------------------------------------------------------ depth tracking

def test_bracket_depths_ignores_brackets_inside_strings():
    lines = ['x = f("((((")', 'y = 1']
    assert bracket_depths(lines) == [0, 0]


def test_bracket_depths_ignores_brackets_inside_comments():
    lines = ['x = 1  // ((( unbalanced', 'y = 2']
    assert bracket_depths(lines) == [0, 0]


def test_bracket_depths_accumulates_across_lines():
    lines = ['x = f(a,', '    b,', '    c)', 'y = 1']
    assert bracket_depths(lines) == [1, 1, 0, 0]


# ------------------------------------------------------------- other rules

def test_declaration_inside_block_is_flagged(tmp_path):
    p = tmp_path / "e.pine"
    p.write_text("if cond\n    row(int i) =>\n", encoding="utf-8")
    assert [f.rule for f in lint(str(p))] == ["declaration-inside-block"]


def test_unbalanced_statement_is_flagged(tmp_path):
    p = tmp_path / "f.pine"
    p.write_text("x = foo(a\ny = 1\n", encoding="utf-8")
    assert "unbalanced-statement" in {f.rule for f in lint(str(p))}


def test_deleted_ternary_rule_is_gone():
    assert "bare-ternary-before-comma" not in {r.__name__ for r in RULES}
    import lint_pine
    assert not hasattr(lint_pine, "rule_bare_ternary_before_comma")
