from services.system_config.store import ConfigStore


def test_load_missing_file_returns_empty(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    assert s.load() == {}


def test_save_and_load_roundtrip(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.save({"LLM_DEEPSEEK_API_KEY": "sk-x", "LLM_DEFAULT_CHANNEL": "DEEPSEEK"})
    assert s.load() == {
        "LLM_DEEPSEEK_API_KEY": "sk-x",
        "LLM_DEFAULT_CHANNEL": "DEEPSEEK",
    }


def test_set_one(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.set("LLM_DEFAULT_CHANNEL", "DEEPSEEK")
    assert s.get("LLM_DEFAULT_CHANNEL") == "DEEPSEEK"


def test_get_default(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    assert s.get("MISSING", "fallback") == "fallback"


def test_delete_keys(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.save({"A": "1", "B": "2"})
    s.delete(["A"])
    assert s.load() == {"B": "2"}


def test_atomic_write_no_partial_file(tmp_path):
    p = tmp_path / "cfg.yaml"
    s = ConfigStore(p)
    s.save({"K": "v"})
    assert not (tmp_path / "cfg.yaml.tmp").exists()
    assert p.read_text(encoding="utf-8").strip() != ""


def test_values_coerced_to_str(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.save({"A": 1, "B": True, "C": "hi"})
    assert s.load() == {"A": "1", "B": "True", "C": "hi"}
