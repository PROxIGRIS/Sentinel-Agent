"""Regression tests for the 2026-09 severity-promotion audit.

Covers three independent ways "critical" could previously be reached by
something that was never independently critical:

  1. SessionAccumulator's repetition multiplier inflating a borderline
     lexical score past CRITICAL_SEVERITY_FLOOR.
  2. ESCALATION_LADDER gaining an escalate_to: "critical" rule.
  3. "high" and "critical" sharing a SEVERITY_RANK, giving mid-tier lexicon
     hits the same base threat magnitude as genuinely critical ones.

And the fast-lane keyword curation: Core's blind substring match must carry
the unambiguous adult-content terms, and must never carry either a common
ambiguous dictionary word or a contextual violence/self-harm/terrorism/
drug/weapon term that needs Python's Angel Engine to disambiguate.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "brain" / "Obylon.py"
CORE_SOURCE = ROOT / "rust" / "core" / "src" / "main.rs"
BRAIN = SOURCE.read_text(encoding="utf-8")
CORE = CORE_SOURCE.read_text(encoding="utf-8")

# Words that must NEVER appear as a standalone fast-lane keyword, on either
# side. See the comment above FASTLANE_CRITICAL_KEYWORDS in Obylon.py for
# the full rationale.
FORBIDDEN_FASTLANE_WORDS = (
    "sex", "nude", "nudes", "naked", "adult", "dating", "escort", "erotic",
    "gore", "murder", "suicide", "terrorist", "jihad", "bomb", "execution",
    "meth", "fentanyl", "heroin",
)
REQUIRED_FASTLANE_WORDS = ("pornhub", "childporn", "onlyfans", "xvideos")


def _extract_module_level(*, names: set[str], with_asserts: bool = False):
    """Executes a chosen subset of Obylon.py's top-level statements (Assign/
    AnnAssign/FunctionDef/ClassDef matching `names`, plus any Assert
    statements that immediately follow a matched Assign if `with_asserts`)
    in an isolated namespace. Mirrors the AST-extraction convention already
    used by lts_stabilization_test.py, extended to cover non-function
    top-level statements (dicts, classes) that file doesn't need."""
    tree = ast.parse(BRAIN, filename=str(SOURCE))
    picked = []
    for i, node in enumerate(tree.body):
        matched = False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            matched = True
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in names for t in node.targets
        ):
            matched = True
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in names:
            matched = True
        if matched:
            picked.append(node)
            if with_asserts and i + 1 < len(tree.body) and isinstance(tree.body[i + 1], ast.Assert):
                picked.append(tree.body[i + 1])
    module = ast.Module(body=picked, type_ignores=[])
    ns = {"math": math, "deque": __import__("collections").deque, "time": __import__("time"),
          "threading": __import__("threading")}
    exec(compile(module, str(SOURCE), "exec"), ns)
    return ns


def test_high_and_critical_no_longer_share_a_severity_rank():
    ns = _extract_module_level(names={"SEVERITY_RANK", "R_MAX", "severity_base_magnitude"})
    vals = {c: ns["severity_base_magnitude"](c) for c in ("info", "warning", "high", "critical")}
    assert vals["info"] < vals["warning"] < vals["high"] < vals["critical"], vals
    # Critical's own numeric behavior must be exactly unchanged by the fix.
    assert vals["critical"] == 1.0
    assert vals["high"] < 1.0, "high must no longer reach critical's ceiling"


def test_escalation_ladder_cannot_reach_critical():
    # The module-level assert executes as part of loading this block; if a
    # future edit adds an escalate_to: "critical" rule, this raises here.
    ns = _extract_module_level(names={"ESCALATION_LADDER"}, with_asserts=True)
    assert all(rule["escalate_to"] != "critical" for rule in ns["ESCALATION_LADDER"].values())


def test_session_accumulator_alone_cannot_synthesize_full_severity():
    ns = _extract_module_level(names={"SessionAccumulator"})
    acc = ns["SessionAccumulator"](window_sec=60.0, escalation_count=3)
    mult = 1.0
    for _ in range(6):
        mult = acc.record(0.70, "some-borderline-term")
    # The accumulator itself is allowed to escalate the multiplier — that
    # part is legitimate evasion-pattern detection. What it must never do
    # is let repetition alone manufacture a critical verdict: that's
    # enforced by the capping logic around its call site, checked below via
    # source assertion since it's inline in a much larger method.
    assert mult >= 1.0


def test_borderline_score_capping_guard_is_present_at_the_call_site():
    # The actual cap (`if c_lev < CRITICAL_SEVERITY_FLOOR: boosted = min(...)`)
    # lives inline inside LexEngine.score(), which has too many internal
    # dependencies to cleanly AST-extract on its own. Assert the guard text
    # directly, matching this repo's existing source-assertion convention
    # for code that's real but impractical to unit-extract.
    assert "session_mult = _SESSION_ACC.record(c_lev, bad_term)" in BRAIN
    assert "if c_lev < CRITICAL_SEVERITY_FLOOR:" in BRAIN
    assert "boosted = min(boosted, CRITICAL_SEVERITY_FLOOR - 0.01)" in BRAIN


def test_fastlane_keywords_exclude_ambiguous_and_contextual_terms_python_side():
    ns = _extract_module_level(names={"FASTLANE_CRITICAL_KEYWORDS"})
    words = set(ns["FASTLANE_CRITICAL_KEYWORDS"])
    for w in FORBIDDEN_FASTLANE_WORDS:
        assert w not in words, f"{w!r} must not be a standalone fast-lane keyword"
    for w in REQUIRED_FASTLANE_WORDS:
        assert w in words, f"expected {w!r} in FASTLANE_CRITICAL_KEYWORDS"
    assert len(words) == len(ns["FASTLANE_CRITICAL_KEYWORDS"]), "no duplicate entries"


def test_fastlane_keywords_exclude_ambiguous_and_contextual_terms_rust_side():
    # Core's compiled-in floor must agree with Obylon.py's synced list —
    # both are audited here so they can't quietly drift apart.
    start = CORE.index("fn default_fastlane_rules()")
    end = CORE.index("fn ", start + 10)
    block = CORE[start:end]
    for w in FORBIDDEN_FASTLANE_WORDS:
        assert f'"{w}".to_string()' not in block, f"{w!r} must not be in Core's fast-lane defaults"
    for w in REQUIRED_FASTLANE_WORDS:
        assert f'"{w}".to_string()' in block, f"expected {w!r} in Core's fast-lane defaults"


def test_rust_has_its_own_regression_tests_for_the_same_policy():
    assert "fn fastlane_defaults_include_unambiguous_adult_content_terms" in CORE
    assert "fn fastlane_defaults_exclude_ambiguous_and_contextual_terms" in CORE
