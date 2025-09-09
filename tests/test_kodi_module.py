import kodi


class DummyResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {"result": []}
    def json(self):  # pragma: no cover - trivial
        return self._data


def test_rpc_exception(monkeypatch):
    calls = {"count": 0}
    def boom(*a, **k):
        calls["count"] += 1
        raise RuntimeError("fail")
    monkeypatch.setattr(kodi, "requests", type("R", (), {"post": staticmethod(boom)}))
    # Should swallow and return None
    assert kodi._rpc("Test.Method") is None
    assert calls["count"] == 1


def test_helpers_call_rpc(monkeypatch):
    seen = []
    def fake_rpc(method, params=None):
        seen.append((method, params))
        if method == "Player.GetActivePlayers":
            return {"result": []}  # not playing
        return {"result": True}
    monkeypatch.setattr(kodi, "_rpc", fake_rpc)
    kodi.notify("T", "M")
    kodi.play("/tmp/f.mp4")
    assert kodi.is_playing() is False
    kodi.progress_notify("f.mp4", 50, "10 MB")
    methods = [m for m, _ in seen]
    assert "GUI.ShowNotification" in methods and "Player.Open" in methods
    assert methods.count("GUI.ShowNotification") >= 1
