"""Issue public signed distributor attribution tokens."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import re


def issue_distributor_token(code: str, secret: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", code):
        raise ValueError("invalid distributor code")
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) < 32:
        raise ValueError("signing secret must contain at least 32 bytes")
    digest = hmac.new(secret_bytes, f"v1.{code}".encode("ascii"), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"v1.{code}.{signature}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="Lowercase distributor code, for example d001")
    parser.add_argument(
        "--secret-env",
        default="OPENSQUILLA_DISTRIBUTOR_TOKEN_SECRET",
        help="Environment variable holding the signing secret",
    )
    args = parser.parse_args()
    secret = os.environ.get(args.secret_env, "")
    try:
        token = issue_distributor_token(args.code, secret)
    except ValueError as exc:
        parser.error(f"cannot issue token: {exc}")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
