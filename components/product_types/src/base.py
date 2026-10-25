"""Product type adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping


class ProductCapability(str, Enum):
    """Stable services exposed by a configured product."""

    ANDROID_ADB = "product.android-adb"


@dataclass(frozen=True)
class ProductDomain:
    """Logical domain enabled in one concrete product configuration."""

    domain_id: str
    operating_system: str


@dataclass(frozen=True)
class ProductComponent:
    """Enabled Moulin component relevant to product capability discovery."""

    name: str
    builder_type: str


@dataclass(frozen=True)
class ProductTargetResolverPlan:
    """Command supplied by a product type to discover one runtime endpoint."""

    command: str
    timeout_seconds: int = 60


class ProductTypeAdapter:
    """Base class for product-specific domain and service discovery."""

    type_id = ""
    label = ""
    description = ""

    def domains(self, _components: Iterable[ProductComponent]) -> tuple[ProductDomain, ...]:
        return ()

    def capabilities(self, components: Iterable[ProductComponent]) -> frozenset[ProductCapability]:
        if any(domain.operating_system == "android" for domain in self.domains(components)):
            return frozenset({ProductCapability.ANDROID_ADB})
        return frozenset()

    def android_adb_resolver(
        self,
        _board: Mapping[str, Any],
    ) -> ProductTargetResolverPlan | None:
        return None
