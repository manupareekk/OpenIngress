"""Tests for composite overall agent score."""

from app.services.agent_readiness_score import compute_overall_agent_score


def test_overall_crawl_only_uses_static_operability():
    scored = compute_overall_agent_score(
        agent_accessibility_score=75.76,
        agent_speed_score=91.9,
        static_audits={"pass_ratio": 0.75, "passed": 3, "total": 4},
    )
    assert scored["crawl_base_score"] == 80.6
    assert scored["overall_score"] < 80.6
    assert scored["score_breakdown"]["includes_explore"] is False


def test_overall_explore_rewards_better_activation():
    old = compute_overall_agent_score(
        agent_accessibility_score=75.76,
        agent_speed_score=91.9,
        static_audits={"pass_ratio": 0.75},
        exploration={"aria_match_rate": 0.88, "activation_rate": 0.05},
        agent_report={
            "efficiency": {
                "actions_lost_percent": 17.9,
                "gap_count": 10,
                "high_gaps": 1,
            }
        },
    )
    new = compute_overall_agent_score(
        agent_accessibility_score=75.76,
        agent_speed_score=91.9,
        static_audits={"pass_ratio": 0.75},
        exploration={"aria_match_rate": 0.94, "activation_rate": 0.08},
        agent_report={
            "efficiency": {
                "actions_lost_percent": 0.0,
                "gap_count": 5,
                "high_gaps": 1,
            }
        },
    )
    assert new["overall_score"] > old["overall_score"]
    assert new["score_breakdown"]["includes_explore"] is True
    assert new["score_breakdown"]["explore_delta"] > old["score_breakdown"]["explore_delta"]


def test_zero_actions_lost_is_not_treated_as_missing():
    """0% actions lost must count as best case, not default 100%."""
    perfect = compute_overall_agent_score(
        agent_accessibility_score=75.76,
        agent_speed_score=91.9,
        exploration={"aria_match_rate": 0.94, "activation_rate": 0.08},
        agent_report={"efficiency": {"actions_lost_percent": 0.0, "gap_count": 5, "high_gaps": 1}},
    )
    broken = compute_overall_agent_score(
        agent_accessibility_score=75.76,
        agent_speed_score=91.9,
        exploration={"aria_match_rate": 0.94, "activation_rate": 0.08},
        agent_report={"efficiency": {"gap_count": 5, "high_gaps": 1}},
    )
    assert perfect["overall_score"] > broken["overall_score"]
    assert perfect["score_breakdown"]["actions_lost_percent"] == 0.0
