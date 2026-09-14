"""Render the complete messaging contract with FastStream's documentation UI."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
from faststream.specification import get_asyncapi_html

router = APIRouter(include_in_schema=False)
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs" / "asyncapi.yaml"


@dataclass
class FileSpecification:
    """Adapt our YAML contract to FastStream's public Specification protocol."""

    document: dict[str, Any]

    @property
    def title(self) -> str:
        return self.document["info"]["title"]

    def to_json(self) -> str:
        return json.dumps(self.document)

    def to_jsonable(self) -> dict[str, Any]:
        return self.document

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.document, allow_unicode=True, sort_keys=False)


@router.get("/asyncapi", response_class=HTMLResponse)
def asyncapi_page() -> HTMLResponse:
    specification = FileSpecification(yaml.safe_load(CONTRACT_PATH.read_text()))
    # Documentation only: do not expose an endpoint that publishes to the broker.
    return HTMLResponse(get_asyncapi_html(specification, try_it_out_path=None))


@router.get("/asyncapi.yaml")
async def asyncapi_contract() -> FileResponse:
    return FileResponse(CONTRACT_PATH, media_type="application/yaml")
