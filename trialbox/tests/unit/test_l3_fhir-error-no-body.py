import pytest

from services.adapter.load_fhir import delete_refs


# Helper classes to mock httpx.Client and its response
class DummyResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class DummyClient:
    def __init__(self, response: DummyResponse):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False  # do not suppress exceptions

    def post(self, *args, **kwargs):
        # Ignore the request details; always return the prepared response
        return self._response


def test_delete_refs_exception_leaks_response_text(monkeypatch):
    """
    The current implementation includes up to 500 characters of the server response
    in the RuntimeError message. This test asserts that such response text is NOT
    present; therefore it will FAIL while the defect exists.
    """
    # Create a synthetic response containing clearly identifiable PHI-like data
    phi_text = "PHI-SECRET-DATA-" * 30  # long enough to exceed 500 characters when sliced
    dummy_resp = DummyResponse(status_code=400, text=phi_text)

    # Patch httpx.Client to return our DummyClient with the dummy response
    monkeypatch.setattr("httpx.Client", lambda *args, **kwargs: DummyClient(dummy_resp))

    # Call delete_refs, which should raise RuntimeError with the response text embedded
    with pytest.raises(RuntimeError) as exc_info:
        delete_refs("http://example.com/fhir", ["Patient/123"])

    # The test expects the exception message NOT to contain the PHI text.
    # Since the current code does include it, this assertion will fail,
    # providing proof of the defect.
    assert "PHI-SECRET-DATA-" not in str(exc_info.value)
