"""C004-F4: Runtime validation must enforce 2-4 options and exactly one
recommended option, consistent with the registered JSON schema (minItems: 2,
"exactly one option per question should be recommended").

These tests call the live ``_normalise_questions`` function directly — no
source-grep, no change-detector.  Each test constructs a question payload that
violates the contract and asserts that ``ValueError`` is raised.  Before the
fix the function silently accepts the invalid input; after the fix it rejects
it with an actionable message.
"""
import pytest

from tools.ask_user_questions_tool import _normalise_questions


class TestF4OptionCountValidation:
    """F4: _normalise_questions must reject fewer than 2 options."""

    def test_rejects_single_option(self):
        """One option contradicts the schema's minItems: 2."""
        questions = [
            {
                "question": "Pick one",
                "options": [{"label": "Only choice", "recommended": True}],
            }
        ]
        with pytest.raises(ValueError, match="at least 2"):
            _normalise_questions(questions)

    def test_rejects_empty_options(self):
        """Zero options must be rejected (now requires at least 2)."""
        questions = [{"question": "Q", "options": []}]
        with pytest.raises(ValueError, match="at least 2 options"):
            _normalise_questions(questions)

    def test_accepts_two_options(self):
        """Two options is the minimum valid count."""
        questions = [
            {
                "question": "Pick one",
                "options": [
                    {"label": "A", "recommended": True},
                    {"label": "B"},
                ],
            }
        ]
        cleaned = _normalise_questions(questions)
        assert len(cleaned[0]["options"]) == 2


class TestF4RecommendedCountValidation:
    """F4: _normalise_questions must require exactly one recommended option."""

    def test_rejects_zero_recommended(self):
        """Zero recommended contradicts the 'exactly one' contract."""
        questions = [
            {
                "question": "Pick one",
                "options": [{"label": "A"}, {"label": "B"}],
            }
        ]
        with pytest.raises(ValueError, match="exactly one"):
            _normalise_questions(questions)

    def test_rejects_two_recommended(self):
        """Two recommended is already rejected (existing behaviour)."""
        questions = [
            {
                "question": "Pick one",
                "options": [
                    {"label": "A", "recommended": True},
                    {"label": "B", "recommended": True},
                ],
            }
        ]
        with pytest.raises(ValueError, match="exactly one"):
            _normalise_questions(questions)

    def test_accepts_exactly_one_recommended(self):
        """Exactly one recommended is the only valid count."""
        questions = [
            {
                "question": "Pick one",
                "options": [
                    {"label": "A", "recommended": True},
                    {"label": "B"},
                    {"label": "C"},
                ],
            }
        ]
        cleaned = _normalise_questions(questions)
        recs = [o for o in cleaned[0]["options"] if o["recommended"]]
        assert len(recs) == 1
