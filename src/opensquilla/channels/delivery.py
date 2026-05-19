"""Delivery target resolution for managed channel adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opensquilla.channels.types import DeliveryTargetResolution


def resolve_delivery_target(
    *,
    channels: Mapping[str, Any],
    channel_types: Mapping[str, str],
    target: str,
    to: str = "",
    account_id: str = "",
    thread_id: str = "",
) -> DeliveryTargetResolution:
    """Resolve outbound delivery fields to a concrete channel adapter.

    ``target`` may be a configured adapter entry name, or a channel type such
    as ``slack`` when the type maps to one adapter. ``account_id`` disambiguates
    multi-account channel configs until channels gain first-class account
    grouping.
    """

    target_name = target.strip()
    target_type = target_name.lower()
    account = account_id.strip()
    recipient = to.strip()
    thread = thread_id.strip()

    if not target_name:
        return DeliveryTargetResolution(ok=False, reason="unsupported_target")

    candidates = [
        name
        for name, channel_type in channel_types.items()
        if channel_type.lower() == target_type
    ]
    if account:
        if account not in candidates:
            return DeliveryTargetResolution(ok=False, reason="unsupported_account")
        return _build_delivery_resolution(
            channels=channels,
            adapter_name=account,
            channel_type=target_type,
            to=recipient,
            account_id=account,
            thread_id=thread,
        )

    if target_name in channels:
        adapter_name = target_name
        channel_type = channel_types.get(adapter_name, adapter_name).lower()
        return _build_delivery_resolution(
            channels=channels,
            adapter_name=adapter_name,
            channel_type=channel_type,
            to=recipient,
            account_id=account,
            thread_id=thread,
        )

    if not candidates:
        return DeliveryTargetResolution(ok=False, reason="unsupported_target")
    if len(candidates) > 1:
        return DeliveryTargetResolution(ok=False, reason="ambiguous_account")

    return _build_delivery_resolution(
        channels=channels,
        adapter_name=candidates[0],
        channel_type=target_type,
        to=recipient,
        account_id=account,
        thread_id=thread,
    )


def _build_delivery_resolution(
    *,
    channels: Mapping[str, Any],
    adapter_name: str,
    channel_type: str,
    to: str,
    account_id: str,
    thread_id: str,
) -> DeliveryTargetResolution:
    if thread_id and channel_type not in {"slack"}:
        return DeliveryTargetResolution(ok=False, reason="unsupported_thread")
    return DeliveryTargetResolution(
        ok=True,
        adapter=channels.get(adapter_name),
        adapter_name=adapter_name,
        channel_type=channel_type,
        to=to,
        account_id=account_id,
        thread_id=thread_id,
    )
