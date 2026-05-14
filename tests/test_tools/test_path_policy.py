from __future__ import annotations

import pytest

from opensquilla.tools.path_policy import is_foreign_host_path


@pytest.mark.parametrize(
    "path",
    [
        "/Users/a1/Desktop/report.pptx",
        "/home/a1/report.txt",
        "/mnt/c/Users/a1/report.txt",
        "/cygdrive/c/Users/a1/report.txt",
        "/c/Users/a1/report.txt",
        "file:///Users/a1/Desktop/report.pptx",
    ],
)
def test_windows_rejects_foreign_posix_like_paths(path: str) -> None:
    assert is_foreign_host_path(path, platform="nt") is True


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\a1\report.txt",
        r"\\server\share\report.txt",
        "//server/share/report.txt",
        "reports/report.txt",
    ],
)
def test_windows_keeps_native_and_relative_paths(path: str) -> None:
    assert is_foreign_host_path(path, platform="nt") is False


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\a1\report.txt",
        r"D:/work/report.txt",
        "file:///C:/Users/a1/report.txt",
    ],
)
def test_posix_rejects_foreign_windows_like_paths(path: str) -> None:
    assert is_foreign_host_path(path, platform="posix") is True


@pytest.mark.parametrize(
    "path",
    [
        "/Users/a1/Desktop/report.pptx",
        "/home/a1/report.txt",
        "reports/report.txt",
    ],
)
def test_posix_keeps_native_and_relative_paths(path: str) -> None:
    assert is_foreign_host_path(path, platform="posix") is False
