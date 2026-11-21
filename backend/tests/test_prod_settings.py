"""Production settings refuse to start when misconfigured, and switch on HTTPS protections."""

import importlib
import sys

import pytest

GOOD_KEY = "k" * 50


def load_prod(monkeypatch, **env):
    monkeypatch.setenv("SIMBOT_LLM", "openai")
    for name in ("DJANGO_SECRET_KEY", "ALLOWED_HOSTS", "USE_HTTPS", "CSRF_TRUSTED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    from config.settings import base

    importlib.reload(base)
    sys.modules.pop("config.settings.prod", None)
    return importlib.import_module("config.settings.prod")


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    monkeypatch.undo()
    sys.modules.pop("config.settings.prod", None)
    from config.settings import base

    importlib.reload(base)


@pytest.mark.parametrize("key", ["", "django-insecure-" + "x" * 40, "short"])
def test_refuses_a_missing_or_weak_secret_key(monkeypatch, key):
    with pytest.raises(RuntimeError, match="DJANGO_SECRET_KEY"):
        load_prod(monkeypatch, DJANGO_SECRET_KEY=key, ALLOWED_HOSTS="training.example.com")


def test_refuses_to_start_without_allowed_hosts(monkeypatch):
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        load_prod(monkeypatch, DJANGO_SECRET_KEY=GOOD_KEY)


def test_https_protections_are_on_and_csrf_trusts_the_site(monkeypatch):
    prod = load_prod(monkeypatch, DJANGO_SECRET_KEY=GOOD_KEY, ALLOWED_HOSTS="training.example.com")
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE
    assert prod.SECURE_SSL_REDIRECT and prod.SECURE_HSTS_SECONDS > 0
    assert prod.CSRF_TRUSTED_ORIGINS == ["https://training.example.com"]
    assert prod.ALLOW_ATTEMPT_RESET is False
    assert prod.ENFORCE_PASSWORD_CHANGE is True


def test_a_plain_http_trial_turns_secure_cookies_off(monkeypatch):
    prod = load_prod(
        monkeypatch, DJANGO_SECRET_KEY=GOOD_KEY, ALLOWED_HOSTS="10.0.0.5", USE_HTTPS="false"
    )
    assert not prod.SESSION_COOKIE_SECURE
    assert not prod.SECURE_SSL_REDIRECT
    assert prod.SECURE_HSTS_SECONDS == 0
