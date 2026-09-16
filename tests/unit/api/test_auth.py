import pytest

from docs.api.auth import AuthError, Principal, bearer_auth, require_scopes


def validator(token: str) -> Principal | None:
    return Principal("user-1", frozenset({"documents:read"})) if token == "good" else None


def test_bearer_auth_is_case_insensitive():
    assert bearer_auth({"authorization": "bEaReR good"}, validator).subject == "user-1"


def test_auth_error_exposes_challenge_via_router():
    from docs.api.http import Request, Router
    router = Router()
    router.route("GET", "/private")(lambda request: bearer_auth(request.headers, validator))
    response = router.dispatch(Request("GET", "/private"))
    assert response.status == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic good"}, {"Authorization": "Bearer "}])
def test_bearer_auth_rejects_missing_or_wrong_scheme(headers):
    with pytest.raises(AuthError) as error:
        bearer_auth(headers, validator)
    assert error.value.status == 401


def test_invalid_token_and_missing_scope_are_safe():
    with pytest.raises(AuthError, match="invalid"):
        bearer_auth({"Authorization": "Bearer bad"}, validator)
    principal = bearer_auth({"Authorization": "Bearer good"}, validator)
    assert require_scopes(principal, "documents:read") is principal
    with pytest.raises(AuthError) as error:
        require_scopes(principal, "documents:write")
    assert error.value.status == 403
