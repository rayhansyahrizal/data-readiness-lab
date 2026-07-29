"""Command-line entry point for deterministic fixture generation."""

import argparse
from pathlib import Path

from .generator import generate_fixture_pack


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic TokoNusantara source pack")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--fixture-version", required=True)
    parser.add_argument("--seed", required=True, type=int)
    args = parser.parse_args()
    manifest = generate_fixture_pack(args.output_dir, args.fixture_version, args.seed)
    print(args.output_dir / "manifest.json")
    print(f"generated {manifest['physical_rows']} physical rows")


if __name__ == "__main__":
    main()
