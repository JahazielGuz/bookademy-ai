import pytest
from pydantic import ValidationError

from app.schemas import Exercise, ExerciseStep, QuizQuestion


def step(number: int, starter: str, expected: str) -> ExerciseStep:
    return ExerciseStep(
        number=number,
        instruction_markdown="Do the thing.",
        explanation_markdown="It does a thing.",
        starter_code=starter,
        expected_code=expected,
    )


def test_broken_step_chain_is_relinked():
    """The model is told steps are cumulative but does not always comply."""
    exercise = Exercise(
        title="Scopes",
        scenario_markdown="A paint shop.",
        language="python",
        steps=[
            step(1, "", "color = 'Red'"),
            step(2, "WRONG", "color = 'Red'\nprint(color)"),
        ],
    )
    assert exercise.steps[1].starter_code == exercise.steps[0].expected_code


def test_steps_are_renumbered_densely():
    exercise = Exercise(
        title="Scopes",
        scenario_markdown="A paint shop.",
        language="python",
        steps=[step(7, "", "a = 1"), step(9, "a = 1", "a = 1\nb = 2")],
    )
    assert [s.number for s in exercise.steps] == [1, 2]


def test_first_step_starter_is_left_alone():
    exercise = Exercise(
        title="Scopes",
        scenario_markdown="A paint shop.",
        language="python",
        steps=[step(1, "# given to you\n", "# given to you\nx = 1")],
    )
    assert exercise.steps[0].starter_code == "# given to you\n"


def test_quiz_answer_must_point_at_a_real_choice():
    with pytest.raises(ValidationError):
        QuizQuestion(
            prompt="Which?", choices=["a", "b"], correct_index=2, explanation="..."
        )
