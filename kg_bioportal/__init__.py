"""Init KG-Bioportal main functions."""

from .download import download
from .transform import transform

__all__ = [
    "download", "transform"
]
