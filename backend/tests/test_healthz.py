import pytest


@pytest.mark.django_db
def test_healthz_answers_without_signing_in(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.django_db
@pytest.mark.parametrize("host", ["localhost", "not-an-allowed-host.example"])
def test_healthz_answers_whatever_the_host(client, settings, host):
    """Docker and monitors probe from inside the server with their own Host header."""
    settings.ALLOWED_HOSTS = ["training.example.com"]
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/healthz", HTTP_HOST=host)
    assert response.status_code == 200


@pytest.mark.django_db
def test_other_paths_still_check_the_host(client, settings):
    settings.ALLOWED_HOSTS = ["training.example.com"]
    assert client.get("/api/v1/progress/summary/", HTTP_HOST="evil.example").status_code == 400
