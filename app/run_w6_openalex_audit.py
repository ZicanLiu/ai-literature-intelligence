"""CLI for the frozen W6 post-freeze OpenAlex query audit.

The live command reads ``OPENALEX_API_KEY`` from the inherited environment only.
It intentionally does not import or call dotenv.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.openalex_client_v2 import OpenAlexClientV2Error
from src.w6_openalex_audit import (
    acquire_and_audit,
    load_and_validate_query_config,
    validate_acquisition_package,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "w6" / "openalex_topic_query_audit_v1.json"
DEFAULT_TOPICS = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha" / "topics.json"
DEFAULT_SPLIT = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha" / "split_manifest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or execute the label-free W6 OpenAlex query audit."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-config", help="Validate frozen query design and bindings.")
    acquire = subparsers.add_parser("acquire", help="Run the bounded live OpenAlex acquisition.")
    acquire.add_argument("--output-dir", type=Path, required=True)
    validate = subparsers.add_parser("validate-package", help="Validate a completed package.")
    validate.add_argument("--package-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-config":
            config, _, _ = load_and_validate_query_config(
                args.config,
                topic_set_path=args.topics,
                split_path=args.split,
            )
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "artifact_id": config["artifact_id"],
                        "config_identity": config["config_identity"],
                        "topic_count": len(config["topics"]),
                        "query_count": sum(
                            len(topic["query_variants"])
                            for topic in config["topics"]
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "acquire":
            api_key = os.getenv("OPENALEX_API_KEY", "")
            manifest = acquire_and_audit(
                config_path=args.config,
                topic_set_path=args.topics,
                split_path=args.split,
                output_dir=args.output_dir,
                api_key=api_key,
            )
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "acquisition_identity": manifest["acquisition_identity"],
                        "query_count": manifest["query_count"],
                        "unique_work_count": manifest["unique_work_count"],
                        "query_hit_count": manifest["query_hit_count"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        manifest = validate_acquisition_package(
            package_dir=args.package_dir,
            config_path=args.config,
            topic_set_path=args.topics,
            split_path=args.split,
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "acquisition_identity": manifest["acquisition_identity"],
                    "query_count": manifest["query_count"],
                    "unique_work_count": manifest["unique_work_count"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except OpenAlexClientV2Error as error:
        print(f"ERROR: {error.summary}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
