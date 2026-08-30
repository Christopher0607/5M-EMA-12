#!/usr/bin/env python3
"""Lint Pine Script for the parser pitfalls that have actually bitten this project.

There is no Pine compiler here, so shipping a script means reasoning about
TradingView's parser rather than running it. Counting brackets across a file is
not enough — the defect that broke `nq_ema12_open.pine` was perfectly balanced.
Every rule below corresponds to a real failure found in this repository, so the
next edit gets checked instead of the user acting as the compiler.

Exit code is non-zero when any ERROR is found.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass


@dataclass
class Finding:
    line: int
    level: str          # "ERROR" | "WARN"
    rule: str
    text: str
    detail: str


def tokenise(raw: str) -> str:
    """Comments dropped, each string literal collapsed to a single token `S`.

    Collapsing to one token matters: with the literal merely skipped, a line
    ending in a string looks like it ends in the operator before it, and the
    continuation rule fires on lines that are perfectly fine.
    """
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c == "/" and i + 1 < len(raw) and raw[i + 1] == "/":
            break
        if c in "\"'":
            quote, i = c, i + 1
            while i < len(raw) and raw[i] != quote:
                i += 1
            i += 1
            out.append("S")
            continue
        out.append(c)
        i += 1
    return "".join(out).rstrip()


CONTINUATION_OPS = ("+", "-", "*", "/", "?", ":", ",", "and", "or",
                    "==", "!=", ">=", "<=", ">", "<")


def rule_continuation_indent(lines: list[str]) -> list[Finding]:
    """A continuation line indented by a multiple of four reads as a new block.

    Pine uses multiples of four for nested blocks, so a continuation must be
    indented by something else (5, 9, 10 ... all fine). Break this and the error
    is `end of line without line continuation (CE10156)` on the *previous* line.
    """
    out = []
    for i, raw in enumerate(lines):
        code = tokenise(raw)
        if not code or code.endswith("=>"):
            continue                      # switch branch / function header
        if not any(code.endswith(op) for op in CONTINUATION_OPS):
            continue
        j = i + 1
        while j < len(lines) and (not lines[j].strip()
                                  or lines[j].strip().startswith("//")):
            j += 1
        if j >= len(lines):
            continue
        indent = len(lines[j]) - len(lines[j].lstrip())
        if indent % 4 == 0:
            out.append(Finding(
                i + 1, "ERROR", "continuation-indent", raw.strip(),
                f"line ends in an operator but the next line is indented "
                f"{indent} spaces, a multiple of 4; Pine reads it as a new "
                f"block, not a continuation"))
    return out


def strip_line(raw: str) -> tuple[str, str | None]:
    """Drop comments and string bodies, keeping structure. Returns (code, open_quote)."""
    out, i, ctx = [], 0, None
    while i < len(raw):
        c = raw[i]
        if ctx is None:
            if c == "/" and i + 1 < len(raw) and raw[i + 1] == "/":
                break
            if c in "\"'":
                ctx = c
                out.append(" ")          # placeholder keeps column-ish alignment
            else:
                out.append(c)
        elif c == ctx:
            ctx = None
        i += 1
    return "".join(out), ctx


def logical_statements(lines: list[str]) -> list[list[tuple[int, str]]]:
    """Group each line with the more-indented lines that continue it."""
    groups: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] | None = None
    cur_indent = 0
    for n, raw in enumerate(lines, 1):
        if not raw.strip() or raw.strip().startswith("//"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if cur is not None and indent > cur_indent:
            cur.append((n, raw))
        else:
            if cur:
                groups.append(cur)
            cur, cur_indent = [(n, raw)], indent
    if cur:
        groups.append(cur)
    return groups


# ── rules ────────────────────────────────────────────────────────────────────

def rule_bare_ternary_before_comma(lines: list[str]) -> list[Finding]:
    """`f(a ? b : c, d)` — the parser cannot tell where the ternary ended.

    TradingView reports this as "Missing closing parenthesis (CE10015)", which
    sends you hunting for a bracket that is not missing.

    Only the genuinely ambiguous shape is an error: a ternary used as a
    POSITIONAL argument followed by another POSITIONAL argument. When the next
    argument is named (`title = ...`), Pine can see where the ternary ended and
    the common `bgcolor(cond ? c : na, title = "x")` idiom compiles fine — so
    flagging that would be crying wolf.
    """
    out = []
    for group in logical_statements(lines):
        # Join the statement so depth survives across continuation lines.
        text, starts = "", []
        for n, raw in group:
            code, _ = strip_line(raw)
            starts.append((len(text), n))
            text += code + " "

        def line_of(pos: int) -> int:
            found = starts[0][1]
            for off, n in starts:
                if off <= pos:
                    found = n
            return found

        depth = 0
        i = 0
        while i < len(text):
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth = max(depth - 1, 0)
            elif c == "?" and depth > 0:
                rest = text[i + 1:]
                if rest.lstrip().startswith("("):
                    i += 1
                    continue                       # already parenthesised
                m = re.match(r"[^?:()]*:[^,()]*,\s*(.{0,24})", rest)
                if m:
                    nxt = m.group(1).lstrip()
                    named = re.match(r"[A-Za-z_]\w*\s*=(?!=)", nxt)
                    if not named:
                        n = line_of(i)
                        out.append(Finding(
                            n, "ERROR", "bare-ternary-before-comma",
                            lines[n - 1].strip(),
                            "ternary is a positional call argument followed by "
                            "another positional argument; wrap it in parentheses "
                            "or hoist it into a variable"))
            i += 1
    return out


def rule_decl_inside_block(lines: list[str]) -> list[Finding]:
    """Pine rejects a function declaration inside a conditional block."""
    out = []
    for n, raw in enumerate(lines, 1):
        code, _ = strip_line(raw)
        if not code.strip() or raw.strip().startswith("//"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent > 0 and re.match(r"\s*[A-Za-z_]\w*\s*\([^)]*\)\s*=>\s*$", code):
            out.append(Finding(
                n, "ERROR", "declaration-inside-block", raw.strip(),
                "function declared inside an indented block; Pine requires "
                "declarations at global scope"))
    return out


def rule_absolute_location_bool(lines: list[str]) -> list[Finding]:
    """`plotshape(<bool>, ..., location.absolute)` draws at zero, off-chart."""
    out = []
    joined = "\n".join(lines)
    for m in re.finditer(r"(plotshape|plotchar)\s*\((.{0,400}?)\)\s*(?:\n|$)",
                         joined, re.S):
        body = m.group(2)
        if "location.absolute" in body:
            first = body.split(",")[0]
            if re.search(r"\b(and|or|not|[<>=!]=|>|<)\b|\bis[A-Z]", first):
                line = joined[:m.start()].count("\n") + 1
                out.append(Finding(
                    line, "ERROR", "absolute-location-with-bool",
                    m.group(0).strip().split("\n")[0],
                    "boolean series with location.absolute plots at 0 and is "
                    "invisible; use location.belowbar / abovebar"))
    return out


def rule_str_format_number(lines: list[str]) -> list[Finding]:
    """`{0,number,00}` style patterns are unreliable in Pine."""
    out = []
    for n, raw in enumerate(lines, 1):
        if re.search(r"\{\d+\s*,\s*number\s*,", raw):
            out.append(Finding(
                n, "WARN", "str-format-number-pattern", raw.strip(),
                "str.format numeric pattern; build the string with "
                "str.tostring instead"))
    return out


def rule_statement_balance(lines: list[str]) -> list[Finding]:
    """Bracket balance per logical statement, not per file."""
    out = []
    for group in logical_statements(lines):
        bal = 0
        unterminated = None
        for n, raw in group:
            code, ctx = strip_line(raw)
            if ctx:
                unterminated = n
            bal += code.count("(") - code.count(")")
            bal += code.count("[") - code.count("]")
        if bal != 0:
            out.append(Finding(
                group[0][0], "ERROR", "unbalanced-statement", group[0][1].strip(),
                f"statement group has net bracket balance {bal:+d}"))
        if unterminated:
            out.append(Finding(
                unterminated, "ERROR", "unterminated-string",
                lines[unterminated - 1].strip(),
                "string literal is not closed on this line"))
    return out


RULES = (rule_bare_ternary_before_comma, rule_decl_inside_block,
         rule_absolute_location_bool, rule_str_format_number,
         rule_statement_balance, rule_continuation_indent)


def lint(path: str) -> list[Finding]:
    lines = open(path, encoding="utf-8").read().split("\n")
    found: list[Finding] = []
    for rule in RULES:
        found.extend(rule(lines))
    return sorted(found, key=lambda f: (f.line, f.level))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    errors = 0
    for path in args.paths:
        found = lint(path)
        if not found:
            print(f"✓ {path}: clean ({len(RULES)} rules)")
            continue
        print(f"{path}:")
        for f in found:
            mark = "✗" if f.level == "ERROR" else "!"
            print(f"  {mark} {f.level:<5} line {f.line:>4}  [{f.rule}]")
            print(f"      {f.text[:100]}")
            print(f"      → {f.detail}")
            errors += f.level == "ERROR"
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
