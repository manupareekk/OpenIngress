from app.models import FlowPage, NavigationTargetKind, ProductActionType
from app.services.navigation_graph_builder import NavigationGraphBuilder
from app.services.operability_metrics import accessibility_from_graph


def test_uncrawled_same_origin_links_are_internal_links_not_dead_targets():
    page = FlowPage(
        id="home",
        path="/",
        title="Google",
        html='<a href="/intl/en/about.html">About Google</a><form action="/search"></form>',
        is_start=True,
        metadata={
            "summary": {
                "actions": [
                    {
                        "id": "about",
                        "tag": "a",
                        "text": "About Google",
                        "attributes": {"href": "/intl/en/about.html"},
                    },
                    {
                        "id": "search",
                        "tag": "form",
                        "text": "Google Search",
                        "action_type": ProductActionType.SUBMIT_FORM.value,
                        "attributes": {"action": "/search"},
                    },
                ]
            }
        },
    )

    graph = NavigationGraphBuilder().build("A", [page], "home").to_dict()
    kinds = {action["id"].split("::")[-1]: action["target_kind"] for action in graph["actions"]}

    assert kinds["about"] == NavigationTargetKind.INTERNAL_LINK.value
    assert kinds["search"] == NavigationTargetKind.FORM_SUBMIT.value
    assert not graph["issues"]


def test_action_accessibility_scores_on_site_actions_without_external_exit_penalty():
    graph = {
        "actions": [
            {"target_kind": NavigationTargetKind.INTERNAL_LINK.value, "page_id": "home"},
            {"target_kind": NavigationTargetKind.FORM_SUBMIT.value, "page_id": "home"},
            {"target_kind": NavigationTargetKind.AUTH_REQUIRED.value, "page_id": "home"},
            {"target_kind": NavigationTargetKind.EXTERNAL_EXIT.value, "page_id": "home"},
            {"target_kind": NavigationTargetKind.EXTERNAL_EXIT.value, "page_id": "home"},
        ],
        "pages": [{"id": "home"}],
    }

    coverage = accessibility_from_graph(graph)

    assert coverage["accessible_actions"] == 2
    assert coverage["total_actions"] == 5
    assert coverage["external_actions"] == 2
    assert coverage["blocked_actions"] == 1
    assert coverage["action_accessibility_percent"] == 66.67
