"""Accounts: sign up, log in, sessions, throttling, and which routes need a login."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import hash_password, read_session, sign_session, verify_password
from app.config import Settings
from app.main import create_app

ALICE = {"name": "Alice Dispatcher", "email": "Alice@Example.org", "password": "correct horse 42"}


@pytest.fixture
def client(settings: Settings):  # type: ignore[no-untyped-def]
    with TestClient(create_app(settings.model_copy(update={"auth_required": True}))) as test_client:
        yield test_client


def test_password_hashing() -> None:
    stored = hash_password("s3cret-pass")
    assert stored.startswith("scrypt$") and "s3cret-pass" not in stored
    assert verify_password("s3cret-pass", stored) and not verify_password("wrong", stored)
    assert hash_password("s3cret-pass") != stored  # salted
    assert not verify_password("x", "garbage")


def test_session_tokens_are_signed_and_expire() -> None:
    token = sign_session("u_1", "a-long-session-secret", ttl_s=60, now=1000)
    assert read_session(token, "a-long-session-secret", now=1030) == "u_1"
    assert read_session(token, "a-long-session-secret", now=1061) is None  # expired
    assert read_session(token, "another-secret-value", now=1030) is None  # wrong key
    assert read_session(token.replace("u_1", "u_2"), "a-long-session-secret", now=1030) is None  # tampered
    assert read_session(None, "a-long-session-secret") is None


def test_signup_login_me_logout(client: TestClient) -> None:
    assert client.get("/auth/me").json() is None  # visitor, not an error
    created = client.post("/auth/signup", json=ALICE)
    assert created.status_code == 201 and created.json()["email"] == "alice@example.org"
    assert "httponly" in created.headers["set-cookie"].lower()
    assert client.get("/auth/me").json()["name"] == "Alice Dispatcher"
    assert client.post("/auth/signup", json=ALICE).status_code == 409
    client.post("/auth/logout")
    assert client.get("/auth/me").json() is None
    logged_in = client.post("/auth/login", json={"email": "alice@example.org", "password": ALICE["password"]})
    assert logged_in.status_code == 200 and client.get("/auth/me").json()["email"] == "alice@example.org"


def test_signup_validation(client: TestClient) -> None:
    assert client.post("/auth/signup", json={**ALICE, "password": "short"}).status_code == 422
    assert client.post("/auth/signup", json={**ALICE, "email": "not-an-email"}).status_code == 422


def test_failed_logins_are_throttled(client: TestClient) -> None:
    client.post("/auth/signup", json=ALICE)
    client.post("/auth/logout")
    wrong = {"email": ALICE["email"], "password": "nope nope"}
    assert [client.post("/auth/login", json=wrong).status_code for _ in range(5)] == [401] * 5
    right = {"email": ALICE["email"], "password": ALICE["password"]}
    assert client.post("/auth/login", json=right).status_code == 429


def test_dispatcher_routes_need_login_but_citizen_intake_does_not(client: TestClient) -> None:
    for path in ("/incidents", "/alerts", "/reports", "/stats", "/benchmark", "/simulate/status"):
        assert client.get(path).status_code == 401, path
    assert client.post("/reports", json={"text": "aag lagi hai Marina beach"}).status_code == 202
    assert client.get("/health").status_code == 200
    client.post("/auth/signup", json=ALICE)
    assert client.get("/incidents").status_code == 200


def test_websocket_needs_login(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/ws") as ws:
        ws.receive_json()
    assert closed.value.code == 4401
    client.post("/auth/signup", json=ALICE)
    with client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": "aag lagi hai Marina beach"})
        assert ws.receive_json()["type"] == "batch"
