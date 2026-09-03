"""Fixed resource type definitions.

Resource types select different storage and rendering code paths, so they are a
part of the application contract rather than user-managed database content.
Keep their stable values, labels, and display order together in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ResourceStorage = Literal["resource", "photo_activity"]


@dataclass(frozen=True)
class ResourceTypeDefinition:
    value: str
    label: str
    sort_order: int
    storage: ResourceStorage

    def as_option(self) -> dict[str, str | int]:
        option = asdict(self)
        option["sortOrder"] = option.pop("sort_order")
        option.pop("storage")
        return option


RESOURCE_TYPES: tuple[ResourceTypeDefinition, ...] = (
    ResourceTypeDefinition("yearbook", "Yearbook", 10, "resource"),
    ResourceTypeDefinition("photos", "活动照片", 20, "photo_activity"),
    ResourceTypeDefinition("teacher", "老师驾到", 30, "resource"),
    ResourceTypeDefinition("other", "其他资源", 999, "resource"),
)

RESOURCE_TYPE_BY_VALUE = {resource_type.value: resource_type for resource_type in RESOURCE_TYPES}
RESOURCE_ROW_TYPE_VALUES = frozenset(
    resource_type.value for resource_type in RESOURCE_TYPES if resource_type.storage == "resource"
)


def get_resource_type(value: object) -> ResourceTypeDefinition | None:
    """Return a fixed type definition for a normalized machine value."""

    return RESOURCE_TYPE_BY_VALUE.get(str(value or "").strip())


def resource_type_options() -> list[dict[str, str | int]]:
    """Return fresh API dictionaries in the fixed display order."""

    return [resource_type.as_option() for resource_type in RESOURCE_TYPES]
