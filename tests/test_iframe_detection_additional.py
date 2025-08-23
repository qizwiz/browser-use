def test_enumerate_all_frames_error_fallback_to_main(monkeypatch, caplog):
    """When frame enumeration fails, fallback to main frame only."""
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _boom():
        raise RuntimeError("bad enumerate")

    # Replace the internal body with one that raises to force the exception path
    async def _broken_enumerate():
        raise RuntimeError("broken")

    # Monkeypatch the entire method body by raising from inside
    # Create a mock DomService that raises an exception
    class MockDomService:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def _get_targets_for_page(self):
            raise RuntimeError("bad enumerate")

    monkeypatch.setattr("browser_use.dom.service.DomService", MockDomService)
    
    with caplog.at_level(logging.ERROR):
        frames = arun(det._enumerate_all_frames())
        assert len(frames) == 1  # Fallback to main frame only
        assert frames[0].frame_id == "main"
        assert any("Error enumerating frames" in rec.message for rec in caplog.records)