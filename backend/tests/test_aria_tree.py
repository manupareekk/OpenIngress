from app.services.aria_tree import aria_snapshot_for_page


class _BodyLocator:
    def aria_snapshot(self):
        return "- link \"Home\""


class _PageWithoutAriaSnapshot:
    def locator(self, selector):
        assert selector == "body"
        return _BodyLocator()


class _PageWithAriaSnapshot:
    def aria_snapshot(self):
        return "- button \"Continue\""


def test_aria_snapshot_for_page_uses_page_method_when_available():
    assert aria_snapshot_for_page(_PageWithAriaSnapshot()) == "- button \"Continue\""


def test_aria_snapshot_for_page_falls_back_to_body_locator():
    assert aria_snapshot_for_page(_PageWithoutAriaSnapshot()) == "- link \"Home\""
