# Distributor attribution bootstrap contract

Distributor attribution is intentionally deferred to the external bootstrap
installer. The OpenSquilla repository does not download a distributor-specific
artifact and does not currently upload a distributor field.

The future bootstrap integration must preserve first-touch attribution: the
first valid distributor source recorded for an installation is retained across
upgrades and reinstalls, and later sources must not overwrite it. The bootstrap
installer will own the durable receipt and hand only the validated attribution
record to the client telemetry path.

Until that integration is implemented, the existing installation telemetry
continues to emit its original `install` and `version_seen` events, and daily
usage uses the same telemetry service's dedicated `/v1/usage` route and the
unified privacy switch.
