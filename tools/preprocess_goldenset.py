#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from keeper_factory.config import LoadedConfig, load_config  # noqa: E402
from keeper_factory.judge.vocab import DIMENSION_VOCAB_V0  # noqa: E402
from keeper_factory.memory.yaml_io import dump_yaml_dict  # noqa: E402
from keeper_factory.models.generate_json import parse_and_validate, schema_prompt_appendix  # noqa: E402
from keeper_factory.models.llm_api import VLLMAPI  # noqa: E402
from keeper_factory.util.hashing import sha256_hex  # noqa: E402


ALLOWED_CATEGORIES = {"bad", "good", "redline"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
IMPORT_LOG_NAME = "_import_log.jsonl"


@dataclass(frozen=True)
class SourceSpec:
    category: str
    directory: Path


class SceneLabel(BaseModel):
    scene_brief: str


class CandidateDimensionDraft(BaseModel):
    dimension: str
    hint: str


class TargetCardDraft(BaseModel):
    candidate_dimensions: list[CandidateDimensionDraft] = Field(min_length=1, max_length=3)
    must_keep: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    category_note: str


class Prelabeler:
    def __init__(self, loaded: LoadedConfig, *, max_long_edge: int = 1024) -> None:
        if loaded.secrets is None:
            raise RuntimeError("resolved secrets are required for prelabeling")
        self.loaded = loaded
        self.max_long_edge = max_long_edge
        self.model_name = loaded.config.models.defaults.vlm
        self.client = VLLMAPI(
            api_key=loaded.secrets.api_key,
            request_url=loaded.config.models.api.request_url,
            model_name=self.model_name,
            timeout_seconds=loaded.config.models.api.timeout_seconds,
            max_tokens=loaded.config.models.nodes.f1_candidate.max_tokens,
        )
        self.prompts_dir = loaded.prompts_dir
        self.jinja = Environment(
            loader=FileSystemLoader(str(self.prompts_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def prelabel(self, *, image_path: Path, category: str) -> dict[str, Any]:
        image = self._load_np_image(image_path)
        scene_prompt = self._render(
            "p0_prelabel_scene.jinja",
            {"category": category},
        )
        scene = self._generate_json(scene_prompt, image=image, schema=SceneLabel)

        card_prompt = self._render(
            "p0_prelabel_target_card.jinja",
            {
                "category": category,
                "dimension_vocab": sorted(DIMENSION_VOCAB_V0.keys()),
            },
        )
        draft = self._generate_json(card_prompt, image=image, schema=TargetCardDraft)
        cleaned_dimensions = []
        for item in draft.candidate_dimensions:
            dim = item.dimension.strip()
            if dim not in DIMENSION_VOCAB_V0:
                dim = "other"
            cleaned_dimensions.append({"dimension": dim, "hint": item.hint.strip()})
        return {
            "scene_brief": scene.scene_brief.strip(),
            "candidate_dimensions": cleaned_dimensions,
            "must_keep": [v.strip() for v in draft.must_keep if v.strip()],
            "forbidden": [v.strip() for v in draft.forbidden if v.strip()],
            "category_note": draft.category_note.strip(),
            "model_name": self.model_name,
        }

    def _render(self, template_name: str, context: dict[str, Any]) -> str:
        return self.jinja.get_template(template_name).render(**context)

    def _generate_json(self, user_prompt: str, *, image, schema: type[BaseModel]):
        prompt = user_prompt + schema_prompt_appendix(schema)
        raw = self.client.generate(
            images=[image],
            user_prompt=prompt,
            max_long_edge=self.max_long_edge,
        )
        return parse_and_validate(raw, schema)

    @staticmethod
    def _load_np_image(path: Path):
        from numpy import asarray, uint8  # local import keeps startup light

        pil = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        return asarray(pil, dtype=uint8)


def parse_sources(values: list[str]) -> list[SourceSpec]:
    specs: list[SourceSpec] = []
    for raw in values:
        if ":" not in raw:
            raise ValueError(f"invalid --source {raw!r}; expected CATEGORY:DIR")
        category, directory = raw.split(":", 1)
        category = category.strip().lower()
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"unsupported category: {category}")
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"source directory not found: {path}")
        specs.append(SourceSpec(category=category, directory=path))
    return specs


def preprocess_image(source: Path, dest: Path, *, max_edge: int = 2048) -> tuple[str, tuple[int, int]]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    width, height = image.size
    longest = max(width, height)
    if longest > max_edge:
        scale = max_edge / float(longest)
        image = image.resize(
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            Image.Resampling.LANCZOS,
        )
    image.save(dest, format="JPEG", quality=95)
    digest = sha256_hex(dest.read_bytes())
    return digest, image.size


def iter_images(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def next_case_id(goldenset_root: Path) -> str:
    """Allocate next case id; gaps in numbering are allowed."""
    from keeper_factory.goldenset import next_case_id as _next_case_id

    return _next_case_id(goldenset_root)


def load_import_digests(log_path: Path) -> set[str]:
    if not log_path.is_file():
        return set()
    digests: set[str] = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        digest = payload.get("digest")
        if isinstance(digest, str) and digest:
            digests.add(digest)
    return digests


def append_import_log(log_path: Path, payload: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_target_card(
    *,
    case_id: str,
    category: str,
    prelabel: dict[str, Any] | None,
) -> dict[str, Any]:
    if prelabel is None:
        prelabel = {
            "scene_brief": "",
            "candidate_dimensions": [{"dimension": "other", "hint": "待人工补充"}],
            "must_keep": [],
            "forbidden": [],
            "category_note": "待人工补充",
            "model_name": "",
        }
    card = {
        "case_id": case_id,
        "category": category,
        "scene_brief": prelabel["scene_brief"],
        "candidate_dimensions": prelabel["candidate_dimensions"],
        "must_keep": prelabel["must_keep"],
        "forbidden": prelabel["forbidden"],
    }
    note = prelabel["category_note"]
    if category == "bad":
        card["problem_note"] = note
    elif category == "good":
        card["established_note"] = note
    else:
        card["trap_note"] = note
    return card


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess and prelabel goldenset images.")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Input source in format CATEGORY:DIR (CATEGORY in bad/good/redline). Repeatable.",
    )
    parser.add_argument("--config", default=str(REPO_ROOT / "config.json"), help="Path to config.json")
    parser.add_argument("--max-edge", type=int, default=2048, help="Max edge for preprocessing")
    parser.add_argument("--skip-prelabel", action="store_true", help="Only preprocess and create placeholder labels")
    parser.add_argument("--limit", type=int, default=0, help="Optional max images per source (0 = no limit)")
    args = parser.parse_args()

    sources = parse_sources(args.source)
    config_path = Path(args.config).expanduser().resolve()
    loaded = load_config(config_path=config_path, project_root=REPO_ROOT, resolve_secrets=not args.skip_prelabel)
    goldenset_root = loaded.data_root / "goldenset"
    goldenset_root.mkdir(parents=True, exist_ok=True)
    import_log = goldenset_root / IMPORT_LOG_NAME
    seen_digests = load_import_digests(import_log)

    prelabeler: Prelabeler | None = None
    if not args.skip_prelabel:
        prelabeler = Prelabeler(loaded)

    created = 0
    skipped = 0
    for spec in sources:
        count = 0
        for src_image in iter_images(spec.directory):
            if args.limit > 0 and count >= args.limit:
                break
            count += 1
            case_id = next_case_id(goldenset_root)
            case_dir = goldenset_root / case_id
            output_jpg = case_dir / "original.jpg"
            digest, size = preprocess_image(src_image, output_jpg, max_edge=args.max_edge)
            if digest in seen_digests:
                output_jpg.unlink(missing_ok=True)
                case_dir.rmdir()
                skipped += 1
                continue

            prelabel = prelabeler.prelabel(image_path=output_jpg, category=spec.category) if prelabeler else None
            card = build_target_card(case_id=case_id, category=spec.category, prelabel=prelabel)
            dump_yaml_dict(case_dir / "target_card.yaml", card)
            append_import_log(
                import_log,
                {
                    "case_id": case_id,
                    "category": spec.category,
                    "source_path": str(src_image),
                    "digest": digest,
                    "size": {"w": size[0], "h": size[1]},
                    "prelabel_model": prelabel.get("model_name", "") if prelabel else "",
                },
            )
            seen_digests.add(digest)
            created += 1
            print(f"[ADDED] {case_id} <- {src_image} ({size[0]}x{size[1]})")

    print(f"Done. created={created}, skipped={skipped}, goldenset={goldenset_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
