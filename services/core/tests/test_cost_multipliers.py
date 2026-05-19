"""Handler-level + composition tests for the cost-multiplier system.

DB-backed loader is tested indirectly via test_pipelines_router (cost
preview endpoint) — here we exercise pure logic.
"""

import pytest

from services.core.app.pipelines.cost_multipliers import (
    IDENTITY_PCT,
    get_handler,
    registered_types,
)
from services.core.app.pipelines.cost_multipliers.input_field import (
    InputFieldHandler,
    InputFieldParams,
)
from services.core.app.pipelines.cost_resolution import apply_rules


# ---------------------------- registry ---------------------------- #


def test_registry_lists_input_field():
    assert "input_field" in registered_types()


def test_get_handler_known():
    assert isinstance(get_handler("input_field"), InputFieldHandler)


def test_get_handler_unknown_returns_none():
    assert get_handler("does_not_exist") is None


# --------------------- InputFieldHandler ------------------------ #


def test_input_field_known_value_returns_configured_pct():
    h = InputFieldHandler()
    params = {
        "input_field": "num_inference_steps",
        "values": {"2": 70, "4": 100, "8": 150},
    }
    assert h.resolve(params, {"num_inference_steps": 2}) == 70
    assert h.resolve(params, {"num_inference_steps": 4}) == 100
    assert h.resolve(params, {"num_inference_steps": 8}) == 150


def test_input_field_unknown_value_is_identity():
    h = InputFieldHandler()
    params = {"input_field": "steps", "values": {"2": 70, "4": 100, "8": 150}}
    # 6 isn't in the table — never overcharge an unrecognised bucket.
    assert h.resolve(params, {"steps": 6}) == IDENTITY_PCT


def test_input_field_missing_field_is_identity():
    h = InputFieldHandler()
    params = {"input_field": "steps", "values": {"4": 100}}
    assert h.resolve({}, {"steps": 4}) == IDENTITY_PCT  # empty params
    assert h.resolve(params, {}) == IDENTITY_PCT  # missing input field


def test_input_field_string_and_int_both_match():
    h = InputFieldHandler()
    params = {"input_field": "quality", "values": {"high": 150}}
    assert h.resolve(params, {"quality": "high"}) == 150


def test_input_field_invalid_params_falls_back_to_identity():
    h = InputFieldHandler()
    # `values` is the wrong shape -> pydantic rejects, handler returns identity.
    bad = {"input_field": "steps", "values": "not a dict"}
    assert h.resolve(bad, {"steps": 4}) == IDENTITY_PCT


def test_input_field_params_pydantic_rejects_missing_field():
    with pytest.raises(Exception):
        InputFieldParams.model_validate({"values": {"4": 100}})


def test_input_field_params_pydantic_rejects_empty_field_name():
    with pytest.raises(Exception):
        InputFieldParams.model_validate({"input_field": "", "values": {}})


# --------------------- composition (apply_rules) ----------------- #


def test_apply_rules_no_rules_returns_base():
    assert apply_rules(10, [], {"num_inference_steps": 4}) == 10


def test_apply_rules_single_rule():
    rules = [
        ("input_field", {"input_field": "steps", "values": {"8": 150}}),
    ]
    assert apply_rules(10, rules, {"steps": 8}) == 15


def test_apply_rules_two_rules_multiply():
    # 10 * 150/100 * 200/100 = 30
    rules = [
        ("input_field", {"input_field": "quality", "values": {"high": 150}}),
        ("input_field", {"input_field": "resolution", "values": {"4k": 200}}),
    ]
    out = apply_rules(10, rules, {"quality": "high", "resolution": "4k"})
    assert out == 30


def test_apply_rules_unknown_type_treated_as_identity():
    # Typo in DB shouldn't accidentally upcharge.
    rules = [("totally_made_up", {"foo": "bar"})]
    assert apply_rules(10, rules, {}) == 10


def test_apply_rules_inactive_rule_does_not_change_cost():
    # Rule defined, but the input value isn't covered → identity.
    rules = [
        ("input_field", {"input_field": "steps", "values": {"8": 150}}),
    ]
    assert apply_rules(10, rules, {"steps": 4}) == 10


def test_apply_rules_integer_truncation_favours_user():
    # 7 * 70 / 100 = 4.9 → 4.
    rules = [("input_field", {"input_field": "steps", "values": {"2": 70}})]
    assert apply_rules(7, rules, {"steps": 2}) == 4


def test_apply_rules_zero_percent_floors_to_zero():
    rules = [("input_field", {"input_field": "steps", "values": {"2": 0}})]
    assert apply_rules(10, rules, {"steps": 2}) == 0


def test_apply_rules_stack_with_zero_collapses_all():
    # Once cost hits 0, subsequent multipliers can't lift it.
    rules = [
        ("input_field", {"input_field": "free", "values": {"yes": 0}}),
        ("input_field", {"input_field": "high", "values": {"yes": 200}}),
    ]
    assert apply_rules(10, rules, {"free": "yes", "high": "yes"}) == 0
