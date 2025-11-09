thonimport argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from extractors.reddit_parser import RedditMediaExtractor
from outputs.exporters import JSONExporter

BASE_DIR = Path(__file__).resolve().parents[1]

def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_settings(config_path: Path) -> Dict[str, Any]:
    logger = logging.getLogger("runner.config")
    if not config_path.exists():
        logger.warning(
            "Config file %s does not exist. Falling back to built-in defaults.",
            config_path,
        )
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as f:
            settings = json.load(f)
        if not isinstance(settings, dict):
            raise ValueError("Root of settings JSON must be an object")
        logger.info("Loaded configuration from %s", config_path)
        return settings
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load config from %s: %s", config_path, exc)
        return {}

def load_input(input_path: Path) -> List[Dict[str, Any]]:
    logger = logging.getLogger("runner.input")
    if not input_path.exists():
        logger.error("Input file %s not found.", input_path)
        raise FileNotFoundError(f"Input file not found: {input_path}")

    try:
        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("Input JSON must be an array of objects with 'url' keys.")
        logger.info("Loaded %d URL entries from %s", len(data), input_path)
        return data
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse JSON from %s: %s", input_path, exc)
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error while reading %s: %s", input_path, exc)
        raise

def parse_args(argv: List[str]) -> argparse.Namespace:
    default_input = BASE_DIR / "data" / "input.sample.json"
    default_output = BASE_DIR / "data" / "sample_output.json"
    default_config = BASE_DIR / "src" / "config" / "settings.example.json"

    parser = argparse.ArgumentParser(
        description="Reddit Media Downloader - Batch media metadata extractor"
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=default_input,
        help=f"Path to input JSON file (default: {default_input})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_output,
        help=f"Path to output JSON file (default: {default_output})",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=default_config,
        help=f"Path to config JSON (default: {default_config})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-v, -vv).",
    )
    return parser.parse_args(argv)

def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    setup_logging(args.verbose)
    logger = logging.getLogger("runner")

    settings = load_settings(args.config)
    reddit_settings = settings.get("reddit", {}) if isinstance(settings, dict) else {}

    extractor = RedditMediaExtractor(
        user_agent=reddit_settings.get(
            "user_agent", "RedditMediaDownloader/1.0 (by u/example)"
        ),
        timeout=float(reddit_settings.get("timeout", 10.0)),
    )

    try:
        input_entries = load_input(args.input)
    except Exception:
        return 1

    urls = [entry["url"] for entry in input_entries if isinstance(entry, dict) and "url" in entry]

    if not urls:
        logger.error("No valid 'url' entries found in input file %s.", args.input)
        return 1

    logger.info("Starting extraction for %d URLs.", len(urls))
    results = extractor.process_batch(urls)

    exporter = JSONExporter()
    try:
        exporter.export(results, args.output)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write output file %s: %s", args.output, exc)
        return 1

    success_count = sum(1 for r in results if not r.get("result", {}).get("error"))
    failure_count = len(results) - success_count

    logger.info(
        "Extraction complete. Success: %d | Failed: %d | Output: %s",
        success_count,
        failure_count,
        args.output,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())