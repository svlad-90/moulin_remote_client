"""Public product type API."""

from components.product_types.api.base import ProductCapability, ProductComponent, ProductDomain, ProductTypeAdapter
from components.product_types.api.registry import ProductTypeRegistry, product_type_registry

__all__ = [
    "ProductCapability",
    "ProductComponent",
    "ProductDomain",
    "ProductTypeAdapter",
    "ProductTypeRegistry",
    "product_type_registry",
]
