from __future__ import annotations

from types import SimpleNamespace

from opensquilla.sandbox.backend import linux_exec_wrapper


def test_exec_wrapper_limits_skip_address_space_cap(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = SimpleNamespace(
        RLIMIT_CPU=0,
        RLIMIT_AS=1,
        RLIMIT_NPROC=2,
        RLIM_INFINITY=-1,
        getrlimit=lambda _resource_id: (-1, -1),
        setrlimit=lambda resource_id, limits: calls.append((resource_id, limits)),
    )
    monkeypatch.setattr(linux_exec_wrapper, "resource", fake_resource)

    linux_exec_wrapper._apply_limits(
        {
            "cpuSeconds": 7,
            "memoryMb": 64,
            "pids": 23,
        }
    )

    assert calls == [
        (0, (7, -1)),
        (2, (23, -1)),
    ]
