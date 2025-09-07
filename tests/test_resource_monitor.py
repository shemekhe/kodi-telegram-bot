import utils


def test_has_enough_space_true(monkeypatch):
    # free_disk_mb returns 1000 -> after subtracting file (400MB) leaves 600 >= 200
    monkeypatch.setattr(utils, "free_disk_mb", lambda p: 1000)
    assert utils.has_enough_space("/x", 400 * 1024 * 1024, 200) is True


def test_has_enough_space_false(monkeypatch):
    # free 300 -> after subtracting 150MB leaves 150 < 200
    monkeypatch.setattr(utils, "free_disk_mb", lambda p: 300)
    assert utils.has_enough_space("/x", 150 * 1024 * 1024, 200) is False


def test_memory_warning(monkeypatch):
    # Reset internal timer
    utils._last_mem_warn = 0  # type: ignore[attr-defined]

    class VM:  # simple structure to mimic psutil result
        def __init__(self, percent):
            self.percent = percent

    seq = [85, 95, 95]  # first below threshold -> False, then above -> True, then rate limited -> False

    def fake_vm():
        return VM(seq.pop(0))

    monkeypatch.setattr(utils.psutil, "virtual_memory", fake_vm)  # type: ignore
    assert utils.maybe_memory_warning(90) is False
    assert utils.maybe_memory_warning(90) is True
    # Third call within 60s should be suppressed
    assert utils.maybe_memory_warning(90) is False


def test_memory_warning_disabled():
    # threshold 0 disables
    assert utils.maybe_memory_warning(0) is False


def test_cleanup_old_files(tmp_path, monkeypatch):
    # Create files with different mtimes
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f3 = tmp_path / "c.bin"
    f1.write_bytes(b"0" * 10)
    f2.write_bytes(b"0" * 10)
    f3.write_bytes(b"0" * 10)
    # Stagger mtimes
    import os
    import time
    now = time.time()
    os.utime(f1, (now - 300, now - 300))
    os.utime(f2, (now - 200, now - 200))
    os.utime(f3, (now - 100, now - 100))

    # Fake free space decreasing until deletions happen
    frees = [50, 50, 120, 300]  # simulate rising free space as files deleted

    def fake_free(_p):
        return frees.pop(0)

    monkeypatch.setattr(utils, "free_disk_mb", fake_free)
    deleted = utils.cleanup_old_files(str(tmp_path), 250)
    # Should delete at least two oldest files to reach target
    assert deleted >= 2
