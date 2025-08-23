async def _boom(_tid: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(det, "_calculate_iframe_offset", _boom)
    
    with caplog.at_level(logging.ERROR):
        ctx = arun(det._get_iframe_context("target-err"))
        assert ctx is None
        assert any("Error getting iframe context" in rec.message for rec in caplog.records)