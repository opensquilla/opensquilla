from __future__ import annotations

import pytest

from opensquilla.secrets import clean_header_secret


def test_clean_header_secret_strips_trailing_paste_punctuation() -> None:
    assert clean_header_secret(" sk-test、\n", label="API key") == "sk-test"


def test_clean_header_secret_strips_leading_paste_punctuation() -> None:
    assert clean_header_secret("：sk-test", label="API key") == "sk-test"
    assert clean_header_secret("、sk-test", label="API key") == "sk-test"


def test_clean_header_secret_rejects_non_ascii_inside_value() -> None:
    with pytest.raises(ValueError, match="non-ASCII"):
        clean_header_secret("sk-测-test", label="API key")
