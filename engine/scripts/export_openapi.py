"""Write contracts/openapi.json and contracts/screen.schema.json (run via `make contracts`)."""

import json
import sys
from pathlib import Path
from typing import Any

from glint.api.app import create_app
from glint.contracts.screen import Screen
from glint.core.settings import REPO_ROOT


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    out = REPO_ROOT / "contracts"
    write_json(out / "openapi.json", create_app().openapi())
    schema = Screen.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://glint.local/contracts/screen.schema.json"
    write_json(out / "screen.schema.json", schema)
    print(f"wrote {out / 'openapi.json'} and {out / 'screen.schema.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
