"""Keep framework and storage dependencies outside the business layers."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        (
            "domain",
            ("app.application", "app.infrastructure", "app.api", "app.bootstrap", "app.config"),
        ),
        ("application", ("app.infrastructure", "app.api", "app.bootstrap", "app.config")),
        ("api", ("app.infrastructure",)),
    ],
)
def test_layer_dependencies(layer, forbidden):
    if layer != "api":
        forbidden += ("sqlalchemy", "httpx", "fastapi", "faststream", "pydantic")
    for path in (APP / layer).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Use explicit imports in {path}"
                imports = [node.module or ""]
                imports += [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                continue
            for name in imports:
                assert not any(name == p or name.startswith(p + ".") for p in forbidden), (
                    f"{path.relative_to(APP)} imports {name}"
                )
