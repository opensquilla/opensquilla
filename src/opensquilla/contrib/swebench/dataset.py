"""Load and filter SWE-bench datasets."""

import logging
from pathlib import Path

from datasets import load_dataset

from opensquilla.contrib.swebench.config import DEFAULT_SPLIT

logger = logging.getLogger(__name__)


def load_instances(
    dataset_name: str,
    split: str = DEFAULT_SPLIT,
    instance_ids: list[str] | None = None,
    instance_file: str | None = None,
) -> list[dict]:
    """Load SWE-bench instances from HuggingFace, with optional filtering.

    Args:
        dataset_name: HuggingFace dataset name
            (e.g. "princeton-nlp/SWE-bench_Verified").
        split: Dataset split (default "test").
        instance_ids: If provided, only keep these instance IDs.
        instance_file: Path to a text file with one instance ID per line.
            Merged with instance_ids if both are provided.

    Returns:
        List of instance dicts, each containing at least:
        instance_id, repo, base_commit, problem_statement.
    """
    # Merge instance_ids from arguments and file
    filter_ids = set(instance_ids or [])
    if instance_file:
        path = Path(instance_file)
        if not path.exists():
            raise FileNotFoundError(f"Instance file not found: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                filter_ids.add(line)

    logger.info("Loading dataset %s (split=%s)...", dataset_name, split)
    ds = load_dataset(dataset_name, split=split)
    logger.info("Loaded %d instances from dataset.", len(ds))

    instances = [dict(row) for row in ds]

    if filter_ids:
        instances = [i for i in instances if i["instance_id"] in filter_ids]
        logger.info("Filtered to %d instances.", len(instances))
        missing = filter_ids - {i["instance_id"] for i in instances}
        if missing:
            logger.warning("Requested but not found in dataset: %s", missing)

    return instances
