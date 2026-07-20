from services.temperature_utils import (
    is_temperature_input_key,
    normalize_temperature_celsius,
    resolve_highest_temperature_c,
)


def test_is_temperature_input_key():
    assert is_temperature_input_key("temp1_input")
    assert is_temperature_input_key("Temp2_Input")
    assert not is_temperature_input_key("in0_input")
    assert not is_temperature_input_key("power1_input")
    assert not is_temperature_input_key("fan1_input")


def test_normalize_temperature_celsius():
    assert normalize_temperature_celsius(45.2) == 45.2
    assert normalize_temperature_celsius(45200) == 45.2
    assert normalize_temperature_celsius(8000000) is None
    assert normalize_temperature_celsius(12.0) is None
    assert normalize_temperature_celsius("bad") is None


def test_resolve_highest_temperature_c_ignores_bad_cache():
    temp_data = {
        "highest_c": 8000000,
        "highest": 8000000,
        "readings": [
            {"sensor": "Package id 0", "temperature_c": 42.0},
            {"sensor": "Core 0", "temperature_c": 8000000},
        ],
    }
    assert resolve_highest_temperature_c(temp_data) == 42.0


def test_resolve_highest_temperature_c_from_valid_highest():
    temp_data = {"highest_c": 67.3, "readings": []}
    assert resolve_highest_temperature_c(temp_data) == 67.3
