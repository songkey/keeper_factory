from __future__ import annotations

from pathlib import Path

from keeper_factory.memory.ids import TYPE_PREFIX, knowledge_type_from_id, next_knowledge_id
from keeper_factory.memory.yaml_io import dump_yaml_dict, load_yaml_dict
from keeper_factory.schemas.enums import KnowledgeType
from keeper_factory.schemas.knowledge import KnowledgeDocument


class MemoryStore:
    SUBDIRS: dict[KnowledgeType, str] = {
        KnowledgeType.CASE_RECIPE: "case_recipes",
        KnowledgeType.PATTERN_PATCH: "pattern_patches",
        KnowledgeType.FAILURE_NOTE: "failure_notes",
        KnowledgeType.CAPABILITY_NOTE: "capability_notes",
    }

    def __init__(self, data_root: Path, *, exp_name: str | None = None) -> None:
        self.exp_name = (exp_name or "").strip() or None
        self.root = data_root / "memory"
        if self.exp_name is not None:
            self.root = self.root / "exp" / self.exp_name
        for subdir in self.SUBDIRS.values():
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

    def _type_dir(self, knowledge_type: KnowledgeType) -> Path:
        return self.root / self.SUBDIRS[knowledge_type]

    def path_for(self, knowledge_id: str) -> Path:
        knowledge_type = knowledge_type_from_id(knowledge_id)
        return self._type_dir(knowledge_type) / f"{knowledge_id}.yaml"

    def list_ids(self, knowledge_type: KnowledgeType | None = None) -> list[str]:
        types = [knowledge_type] if knowledge_type is not None else list(self.SUBDIRS)
        ids: list[str] = []
        for item_type in types:
            for path in sorted(self._type_dir(item_type).glob("*.yaml")):
                ids.append(path.stem)
        return sorted(ids)

    def get(self, knowledge_id: str) -> KnowledgeDocument | None:
        path = self.path_for(knowledge_id)
        if not path.is_file():
            return None
        return KnowledgeDocument.from_yaml_dict(load_yaml_dict(path))

    def save(self, document: KnowledgeDocument) -> Path:
        if self.exp_name is not None and document.exp_name is None:
            document.exp_name = self.exp_name
        path = self.path_for(document.id)
        dump_yaml_dict(path, document.to_yaml_dict())
        return path

    def list_all(self, knowledge_type: KnowledgeType | None = None) -> list[KnowledgeDocument]:
        docs = [doc for doc in (self.get(kid) for kid in self.list_ids(knowledge_type)) if doc is not None]
        if self.exp_name is None:
            return docs
        return [doc for doc in docs if (doc.exp_name or "").strip() == self.exp_name]

    def allocate_id(self, knowledge_type: KnowledgeType) -> str:
        return next_knowledge_id(self.list_ids(knowledge_type), knowledge_type)

    def delete(self, knowledge_id: str) -> bool:
        path = self.path_for(knowledge_id)
        if path.is_file():
            path.unlink()
            return True
        return False
