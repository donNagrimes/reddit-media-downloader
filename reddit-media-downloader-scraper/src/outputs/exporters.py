thonfrom __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List

logger = logging.getLogger("outputs.exporters")

class JSONExporter:
    """
    Writes extraction results to a JSON file.
    """

    def export(self, data: List[Any], output_path: Path) -> None:
        if not isinstance(output_path, Path):
            output_path = Path(output_path)

        if not output_path.parent.exists():
            logger.debug("Creating output directory %s", output_path.parent)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Writing %d records to %s", len(data), output_path)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug("Successfully wrote output JSON to %s", output_path)