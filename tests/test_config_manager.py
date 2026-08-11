import json

from app.config.config_manager import ConfigManager


def make(tmp_path, payload=None):
    path = tmp_path / "config.json"
    if payload is not None:
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
    return ConfigManager(path)


def test_defaults_apply_when_no_file_exists(tmp_path):
    config = make(tmp_path)
    assert config.auto_refresh is True
    assert config.refresh_interval == 5
    assert config.custom_descriptions == {}
    assert config.load_error is None


def test_a_corrupt_file_falls_back_instead_of_crashing(tmp_path):
    config = make(tmp_path, "{ this is not json")
    assert config.refresh_interval == 5
    assert config.load_error and "JSON" in config.load_error


def test_a_non_object_file_is_rejected(tmp_path):
    config = make(tmp_path, "[1, 2, 3]")
    assert config.load_error
    assert config.refresh_interval == 5


def test_valid_settings_are_read(tmp_path):
    config = make(
        tmp_path,
        {
            "auto_refresh": False,
            "refresh_interval": 30,
            "custom_descriptions": {"8000": "AI Backend"},
        },
    )
    assert config.auto_refresh is False
    assert config.refresh_interval == 30
    assert config.custom_descriptions == {"8000": "AI Backend"}


def test_out_of_range_intervals_are_ignored(tmp_path):
    assert make(tmp_path, {"refresh_interval": 1}).refresh_interval == 5
    assert make(tmp_path, {"refresh_interval": 900}).refresh_interval == 5
    assert make(tmp_path, {"refresh_interval": "5"}).refresh_interval == 5


def test_custom_descriptions_are_sanitised(tmp_path):
    config = make(
        tmp_path,
        {
            "custom_descriptions": {
                "8000": "AI Backend",
                " 3000 ": "Frontend",
                "70000": "impossible port",
                "0": "not a port",
                "abc": "not a number",
                "9000": "",
                "9100": 42,
            }
        },
    )
    assert config.custom_descriptions == {"8000": "AI Backend", "3000": "Frontend"}


def test_settings_round_trip_through_the_file(tmp_path):
    config = make(tmp_path)
    config.set_refresh(False, 10)
    config.set_custom_descriptions({"9000": "MCP Server"})

    reloaded = ConfigManager(tmp_path / "config.json")
    assert reloaded.auto_refresh is False
    assert reloaded.refresh_interval == 10
    assert reloaded.custom_descriptions == {"9000": "MCP Server"}


def test_window_state_is_remembered_but_bounded(tmp_path):
    config = make(tmp_path)
    config.set_window_state(1400, 900, False)
    assert ConfigManager(tmp_path / "config.json").window_size == (1400, 900)

    # Absurd sizes never overwrite a usable one.
    config.set_window_state(10, 10, False)
    assert config.window_size == (1400, 900)


def test_maximised_state_does_not_overwrite_the_restored_size(tmp_path):
    config = make(tmp_path)
    config.set_window_state(1400, 900, False)
    config.set_window_state(3840, 2160, True)
    reloaded = ConfigManager(tmp_path / "config.json")
    assert reloaded.window_maximized is True
    assert reloaded.window_size == (1400, 900)


def test_saving_never_leaves_a_partial_file(tmp_path):
    config = make(tmp_path)
    config.set_custom_descriptions({"8080": "Proxy"})
    written = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert written["custom_descriptions"] == {"8080": "Proxy"}
    assert not list(tmp_path.glob(".config-*.tmp"))


def test_the_file_is_created_on_demand(tmp_path):
    config = make(tmp_path)
    assert not config.path.exists()
    assert config.ensure_file_exists() is None
    assert config.path.exists()
