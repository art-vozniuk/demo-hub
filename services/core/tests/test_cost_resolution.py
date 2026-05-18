from services.core.app.pipelines.cost_resolution import resolve_cost


def test_no_rule_returns_base():
    assert resolve_cost(10, None, {"num_inference_steps": 4}) == 10


def test_empty_rule_returns_base():
    assert resolve_cost(10, {}, {"num_inference_steps": 4}) == 10


def test_rule_without_values_returns_base():
    rule = {"input_field": "num_inference_steps"}
    assert resolve_cost(10, rule, {"num_inference_steps": 4}) == 10


def test_known_value_applies_multiplier():
    rule = {
        "input_field": "num_inference_steps",
        "values": {"2": 70, "4": 100, "8": 150},
    }
    assert resolve_cost(10, rule, {"num_inference_steps": 2}) == 7
    assert resolve_cost(10, rule, {"num_inference_steps": 4}) == 10
    assert resolve_cost(10, rule, {"num_inference_steps": 8}) == 15


def test_unknown_input_value_falls_back_to_base():
    # Never overcharge if the rule doesn't cover the value the user sent.
    rule = {
        "input_field": "num_inference_steps",
        "values": {"2": 70, "4": 100, "8": 150},
    }
    assert resolve_cost(10, rule, {"num_inference_steps": 6}) == 10


def test_missing_field_falls_back_to_base():
    rule = {
        "input_field": "num_inference_steps",
        "values": {"4": 100},
    }
    assert resolve_cost(10, rule, {}) == 10


def test_string_and_int_values_both_match():
    rule = {"input_field": "quality", "values": {"high": 150}}
    assert resolve_cost(10, rule, {"quality": "high"}) == 15


def test_malformed_percent_falls_back_to_base():
    rule = {"input_field": "steps", "values": {"4": "not a number"}}
    assert resolve_cost(10, rule, {"steps": 4}) == 10


def test_zero_percent_floors_at_zero():
    rule = {"input_field": "steps", "values": {"2": 0}}
    assert resolve_cost(10, rule, {"steps": 2}) == 0


def test_integer_division_truncates():
    # 7 * 70 // 100 = 4 (not 4.9); cheaper for the user, fine for us.
    rule = {"input_field": "steps", "values": {"2": 70}}
    assert resolve_cost(7, rule, {"steps": 2}) == 4
