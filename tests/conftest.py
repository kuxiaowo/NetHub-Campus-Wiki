import pytest


@pytest.fixture(autouse=True)
def central_account_service(monkeypatch):
    """Existing local fixtures represent active, verified central members."""
    monkeypatch.setattr(
        "nethub_status.read_account_status",
        lambda *args: {"active": True, "emailVerified": True},
    )
