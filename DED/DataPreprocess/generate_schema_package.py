from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_SCHEMA_DIR = SCRIPT_DIR / "schema"
DEFAULT_MANIFEST_PATH = SCRIPT_DIR / "bundle_manifest.json"
ROOT_NAMESPACE = "http://nkust.edu.tw/mislab/final/"
SCHEMA_BASE = "http://nkust.edu.tw/mislab/final/schema/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the Final schema bundle manifest from the current schema files.",
    )
    parser.add_argument(
        "--schema-dir",
        default=str(DEFAULT_SCHEMA_DIR),
        help="Directory that contains *.schema.json files.",
    )
    parser.add_argument(
        "--manifest-path",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Path where bundle_manifest.json will be written.",
    )
    return parser.parse_args()


def load_schemas(schema_dir: Path) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for path in sorted(schema_dir.glob("*.schema.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema_id = payload.get("$id") or f"{SCHEMA_BASE}{path.name}"
        schemas.append(
            {
                "name": path.name,
                "id": schema_id,
                "local_file": str(path.relative_to(SCRIPT_DIR)).replace("\\", "/"),
            }
        )
    return schemas


def build_manifest(schema_dir: Path) -> dict[str, Any]:
    return {
        "metadata": {
            "package_name": "final-nc-schema-package",
            "root_namespace": ROOT_NAMESPACE,
            "schema_base": SCHEMA_BASE,
            "source_format": "Siemens MPF",
            "machine_domain": "laser-directed-energy-deposition",
        },
        "schemas": load_schemas(schema_dir),
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    schema_dir = Path(args.schema_dir).resolve()
    manifest_path = Path(args.manifest_path).resolve()

    if not schema_dir.exists():
        raise SystemExit(f"Schema directory not found: {schema_dir}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(schema_dir)
    write_json(manifest_path, manifest)

    print(f"[OK] wrote {manifest_path.relative_to(SCRIPT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
