"""Tests for catalog activation budget helpers."""

from app.services.catalog_activation import activation_budget_summary, page_type_for_path


def test_page_type_for_path():
    assert page_type_for_path("/") == "home"
    assert page_type_for_path("/writing") == "writing"
    assert page_type_for_path("/pricing") is None


def test_activation_budget_summary():
    universe = {"pages": [{"path": "/"}, {"path": "/writing"}]}
    summary = activation_budget_summary({"home", "writing", "writing_slug"}, universe)
    assert "home" in summary["required"]
    assert summary["complete"] is True
