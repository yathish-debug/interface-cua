from cua.safety.policy import Policy, Decision, Risk


def _p(**kw):
    base = dict(
        allowed_hosts=["localhost:8000"],
        allowed_actions=["navigate", "type", "click"],
        irreversible_routes=["open-subaccount"],
        irreversible_names=["open sub-account", "confirm", "submit"],
        allow_irreversible=False,
    )
    base.update(kw)
    return Policy(**base)


def test_safe_navigate_allowed():
    r = _p().evaluate("navigate", url="http://localhost:8000/")
    assert r.decision is Decision.allow and r.risk is Risk.safe

def test_offhost_blocked():
    assert _p().evaluate("navigate", url="http://evil.com/").decision is Decision.block

def test_bad_action_blocked():
    assert _p().evaluate("download", url="http://localhost:8000/").decision is Decision.block

def test_type_allowed():
    r = _p().evaluate("type", url="http://localhost:8000/", target_name="Member ID")
    assert r.decision is Decision.allow

def test_irreversible_by_name_needs_confirm():
    r = _p().evaluate("click", url="http://localhost:8000/member/12345",
                      target_name="Open Sub-Account")
    assert r.decision is Decision.confirm and r.risk is Risk.irreversible

def test_irreversible_by_route_needs_confirm():
    r = _p().evaluate("navigate", url="http://localhost:8000/member/12345/open-subaccount")
    assert r.decision is Decision.confirm

def test_declared_risk_wins():
    r = _p().evaluate("click", url="http://localhost:8000/", target_name="OK",
                      declared_risk="irreversible")
    assert r.decision is Decision.confirm

def test_approved_irreversible_allowed():
    r = _p(allow_irreversible=True).evaluate("click", url="http://localhost:8000/",
                                             target_name="Confirm")
    assert r.decision is Decision.allow and r.risk is Risk.irreversible
