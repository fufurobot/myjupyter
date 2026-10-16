"""Unit tests for the daily "open a PR only when something changed" logic.

``todo.md`` asks for a GitHub CI matrix that *submits pull requests daily, but
only if there is no remote update*.  The decision is therefore:

    open a PR  <=>  there ARE local changes to propose
                    AND  no open PR already covers them

Testing this as a pure function keeps the rule out of YAML, where it cannot be
tested.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "scripts" / "daily_pr.py"
    if not path.is_file():
        pytest.fail(f"missing implementation file: {path}")
    spec = importlib.util.spec_from_file_location("daily_pr", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["daily_pr"] = module
    spec.loader.exec_module(module)
    return module


dp = _load()


class TestShouldOpenPr:
    def test_no_changes_and_no_open_pr_does_not_open(self):
        assert dp.should_open_pr(diff_lines=0, open_prs=0) is False

    def test_changes_and_no_open_pr_opens(self):
        assert dp.should_open_pr(diff_lines=12, open_prs=0) is True

    def test_changes_but_existing_pr_does_not_open(self):
        assert dp.should_open_pr(diff_lines=12, open_prs=1) is False

    def test_no_changes_but_existing_pr_does_not_open(self):
        assert dp.should_open_pr(diff_lines=0, open_prs=3) is False

    def test_force_opens_even_without_changes(self):
        assert dp.should_open_pr(diff_lines=0, open_prs=0, force=True) is True

    def test_force_does_not_duplicate_an_open_pr(self):
        assert dp.should_open_pr(diff_lines=0, open_prs=1, force=True) is False

    def test_negative_diff_lines_is_treated_as_no_change(self):
        assert dp.should_open_pr(diff_lines=-1, open_prs=0) is False

    @pytest.mark.parametrize("lines", [1, 2, 999])
    def test_any_positive_change_counts(self, lines):
        assert dp.should_open_pr(diff_lines=lines, open_prs=0) is True


class TestBranchNaming:
    def test_branch_name_is_deterministic_for_a_date(self):
        assert dp.daily_branch_name("2025-01-31") == dp.daily_branch_name("2025-01-31")

    def test_branch_name_contains_the_date(self):
        assert "2025-01-31" in dp.daily_branch_name("2025-01-31")

    def test_branch_name_is_a_valid_git_ref(self):
        name = dp.daily_branch_name("2025-01-31")
        assert not name.startswith("/")
        assert not name.endswith("/")
        assert " " not in name
        assert ".." not in name

    def test_branch_names_differ_across_dates(self):
        assert dp.daily_branch_name("2025-01-31") != dp.daily_branch_name("2025-02-01")


class TestPrBody:
    def test_body_mentions_the_changed_targets(self):
        body = dp.build_pr_body(added=[], updated=["unix/archlinux/3.14"], removed=[])
        assert "unix/archlinux/3.14" in body

    def test_body_handles_an_empty_change_set(self):
        body = dp.build_pr_body(added=[], updated=[], removed=[])
        assert isinstance(body, str)

    def test_body_reports_added_and_removed_sections(self):
        body = dp.build_pr_body(
            added=["unix/debian/3.12"], updated=[], removed=["windows/win7/3.10"]
        )
        assert "unix/debian/3.12" in body
        assert "windows/win7/3.10" in body

    def test_body_links_the_tracking_issue(self):
        body = dp.build_pr_body(added=[], updated=[], removed=[], issue=1)
        assert "#1" in body


class TestChangeDetection:
    def test_identical_trees_have_no_diff(self):
        assert dp.diff_targets({"a": "1"}, {"a": "1"}) == ([], [], [])

    def test_new_target_is_added(self):
        added, updated, removed = dp.diff_targets({}, {"a": "1"})
        assert added == ["a"]
        assert updated == []
        assert removed == []

    def test_changed_hash_is_updated(self):
        added, updated, removed = dp.diff_targets({"a": "1"}, {"a": "2"})
        assert updated == ["a"]
        assert added == [] and removed == []

    def test_missing_target_is_removed(self):
        added, updated, removed = dp.diff_targets({"a": "1"}, {})
        assert removed == ["a"]

    def test_results_are_sorted_for_stable_output(self):
        added, _, _ = dp.diff_targets({}, {"b": "1", "a": "1", "c": "1"})
        assert added == ["a", "b", "c"]
