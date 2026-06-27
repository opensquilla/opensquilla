"""SWE-bench harness for OpenSquilla (contrib).

Runs OpenSquilla agents inside official SWE-bench Docker images, collects
patches, and drives the official evaluation harness. Supports
SWE-bench_Verified and SWE-bench_Multilingual.

Optional feature: install extras with ``pip install opensquilla[swebench]``.
Nothing in this package is imported by OpenSquilla's startup path; modules
are loaded on demand by the ``opensquilla swebench`` CLI subcommand.
"""
