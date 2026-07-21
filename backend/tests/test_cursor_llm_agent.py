from app.config import Config
from app.services.cursor_llm_agent import _decide_with_heuristic, llm_explorer_enabled


def test_heuristic_prefers_short_nav_link():
    candidates = [
        {"role": "link", "name": "The Coca-Cola Company careers portal"},
        {"role": "link", "name": "Writing"},
        {"role": "button", "name": "Subscribe"},
    ]
    choice = _decide_with_heuristic(candidates, [])
    assert choice["action"] == "click"
    assert choice["name"] == "Writing"


def test_heuristic_done_when_all_clicked():
    candidates = [{"role": "link", "name": "Home"}]
    history = [{"action": "click", "role": "link", "name": "Home"}]
    choice = _decide_with_heuristic(candidates, history)
    assert choice["action"] == "done"


def test_llm_disabled_without_key(monkeypatch):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(Config, "LLM_API_KEY", "")
    assert llm_explorer_enabled() is False
