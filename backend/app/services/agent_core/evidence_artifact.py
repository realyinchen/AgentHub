from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class EvidenceArtifactWriteError(RuntimeError):
    """Raised when one evidence artifact cannot be created safely."""


class EvidenceArtifactWriter:
    """Preflight and exclusively create one UTF-8 JSON artifact."""

    def require_available(self, path: str | Path) -> Path:
        target = Path(path).resolve()
        if not target.parent.is_dir():
            raise EvidenceArtifactWriteError(
                "evidence_output_parent_missing"
            )
        if target.exists():
            raise EvidenceArtifactWriteError(
                "evidence_output_already_exists"
            )
        return target

    def write_json_new(
        self,
        path: str | Path,
        payload: BaseModel | dict[str, Any],
    ) -> Path:
        target = self.require_available(path)
        value = (
            payload.model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else payload
        )
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        try:
            with target.open("x", encoding="utf-8", newline="\n") as file:
                file.write(rendered)
                file.write("\n")
        except FileExistsError as exc:
            raise EvidenceArtifactWriteError(
                "evidence_output_already_exists"
            ) from exc
        return target


__all__ = [
    "EvidenceArtifactWriteError",
    "EvidenceArtifactWriter",
]
