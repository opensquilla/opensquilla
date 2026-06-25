from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.backend.linux_limits import resource_preexec_from_policy

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Linux resource-limit tests require POSIX platform semantics",
)


def test_resource_preexec_from_policy_sets_cpu_and_pid_limits_without_address_space_cap(
    monkeypatch,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = SimpleNamespace(
        RLIMIT_CPU=0,
        RLIMIT_AS=1,
        RLIMIT_NPROC=2,
        RLIM_INFINITY=-1,
        getrlimit=lambda _resource_id: (-1, -1),
        setrlimit=lambda resource_id, limits: calls.append((resource_id, limits)),
    )
    monkeypatch.setattr(
        "opensquilla.sandbox.backend.linux_limits.resource",
        fake_resource,
    )

    preexec = resource_preexec_from_policy(
        {
            "cpuSeconds": 7,
            "memoryMb": 64,
            "pids": 23,
        }
    )

    assert preexec is not None
    preexec()

    assert calls == [
        (0, (7, -1)),
        (2, (23, -1)),
    ]


def test_resource_preexec_from_policy_returns_none_without_limits() -> None:
    assert resource_preexec_from_policy({}) is None
