#!/usr/bin/env python3
"""run-regression.py — execute the regression fixture suite.

Reads regression-fixtures.yaml, runs validate.py --visual on each unique
deck, parses output for the expected audit + slide, asserts must_fire /
must_not_fire per fixture, prints pass/fail, exits with the failure count.

Use case:
  1. After ANY audit rule edit in validate.py — re-run to verify the rule
     still catches the historical user-complaint cases AND doesn't
     regress on previously-fixed cases.
  2. Periodic CI / pre-push check.

Why this script (vs pytest):
  - Stdlib + PyYAML only; no test framework dependency
  - Cache-aware: runs validate.py at most ONCE per deck (fixtures often
    share the same source deck — pytest would re-run per-test)
  - Per-fixture deterministic output (deck + audit + slide + verdict)
    that's diffable for "what changed since last run"

Usage:
  python3 skills/feishu-deck-h5/tests/run-regression.py
  python3 skills/feishu-deck-h5/tests/run-regression.py --fixtures custom.yaml
  python3 skills/feishu-deck-h5/tests/run-regression.py --verbose
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print('FATAL: PyYAML required. `pip install pyyaml`', file=sys.stderr)
    sys.exit(2)


# Repo root = three levels up from this file (tests/ → assets/.. → skill → skills/ → repo).
# Actually: tests/ is at <repo>/skills/feishu-deck-h5/tests/. Two ups: skill, skills.
SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parent.parent
VALIDATOR = SKILL_ROOT / 'assets' / 'validate.py'
DEFAULT_FIXTURES = SKILL_ROOT / 'tests' / 'regression-fixtures.yaml'


# Parses lines like:
#   ✗ [R-VIS-LABEL-FLOOR] slide 9 · card `article.script-card.is-orange` ...
AUDIT_LINE = re.compile(
    r'[✗!]\s+\[(?P<rule>[A-Z0-9][\w-]*)\]\s+slide\s+(?P<slide>\d+)\b[^\n]*'
)


def load_fixtures(path: Path) -> list:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or 'fixtures' not in data:
        raise SystemExit(f'FATAL: {path} missing top-level `fixtures:` key.')
    return data['fixtures']


def run_validator(deck: Path) -> str:
    """Run validate.py --visual on the deck; return combined stdout+stderr.

    Timeout 420s — handles 50-slide decks comfortably.
    """
    if not deck.exists():
        raise FileNotFoundError(f'deck not found: {deck}')
    proc = subprocess.run(
        ['python3', str(VALIDATOR), str(deck), '--visual'],
        capture_output=True, text=True, timeout=420,
    )
    return proc.stdout + proc.stderr


def parse_audit_hits(output: str) -> dict:
    """Return { (rule_code, slide_idx): [full_line, ...] } from validator output.

    The full_line is kept so selector_hint matching can scan it.
    """
    hits = defaultdict(list)
    for line in output.split('\n'):
        m = AUDIT_LINE.search(line)
        if not m:
            continue
        rule = m.group('rule')
        slide = int(m.group('slide'))
        hits[(rule, slide)].append(line.strip())
    return hits


def evaluate_fixture(fixture: dict, hits: dict) -> tuple:
    """Return (passed: bool, reason: str)."""
    rule = fixture['audit']
    slide = int(fixture['slide'])
    typ = fixture['type']
    hint = fixture.get('selector_hint', '')

    matches = hits.get((rule, slide), [])
    if hint:
        matches = [m for m in matches if hint in m]

    if typ == 'must_fire':
        if matches:
            sample = matches[0][:140] + ('...' if len(matches[0]) > 140 else '')
            return True, f'{len(matches)} hit(s); sample: {sample}'
        return False, (
            f'expected {rule} to fire on slide {slide}'
            + (f' with selector containing `{hint}`' if hint else '')
            + ' — got 0 matching hits'
        )
    if typ == 'must_not_fire':
        if not matches:
            return True, f'no {rule} hits on slide {slide} (as expected)'
        sample = matches[0][:140] + ('...' if len(matches[0]) > 140 else '')
        return False, (
            f'expected {rule} to NOT fire on slide {slide}'
            + (f' with selector containing `{hint}`' if hint else '')
            + f' — got {len(matches)} hit(s); sample: {sample}'
        )
    return False, f'unknown fixture type `{typ}` (must_fire | must_not_fire)'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--fixtures', '-f', type=Path, default=DEFAULT_FIXTURES,
                    help='path to fixtures yaml (default: tests/regression-fixtures.yaml)')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='print sample audit line on every fixture (not just failures)')
    args = ap.parse_args()

    fixtures = load_fixtures(args.fixtures)
    print(f'Loaded {len(fixtures)} fixtures from {args.fixtures.relative_to(REPO_ROOT)}')
    print()

    # Group fixtures by deck to avoid re-running validate.py per fixture.
    by_deck = defaultdict(list)
    for fx in fixtures:
        by_deck[fx['deck']].append(fx)

    pass_count = 0
    fail_count = 0
    for deck_rel, deck_fixtures in by_deck.items():
        deck_path = REPO_ROOT / deck_rel
        print(f'== {deck_rel}  ({len(deck_fixtures)} fixtures) ==')
        try:
            output = run_validator(deck_path)
        except FileNotFoundError as e:
            print(f'  ✗ DECK MISSING — {e}')
            fail_count += len(deck_fixtures)
            continue
        except subprocess.TimeoutExpired:
            print('  ✗ VALIDATOR TIMEOUT (>420s) — visual audit likely stuck')
            fail_count += len(deck_fixtures)
            continue
        hits = parse_audit_hits(output)
        for fx in deck_fixtures:
            ok, reason = evaluate_fixture(fx, hits)
            mark = '✓' if ok else '✗'
            print(f'  {mark} [{fx["audit"]}] {fx["id"]}')
            if not ok or args.verbose:
                print(f'      → {reason}')
            if ok:
                pass_count += 1
            else:
                fail_count += 1
        print()

    print(f'TOTAL: {pass_count} pass · {fail_count} fail')
    sys.exit(fail_count)


if __name__ == '__main__':
    main()
