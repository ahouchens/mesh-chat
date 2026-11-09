"""Standalone, unpublished Mesh Chat Core protocol client."""

from .client import CoreClient
from .errors import CoreClientError
from .types import Acceptance, Composer, ComposerUpdate, DraftAcceptance, ProfileCatalog, ProfileEntry

__version__ = "0.3.0.dev0"
__all__ = ["CoreClient", "CoreClientError", "Acceptance", "Composer", "ComposerUpdate", "DraftAcceptance", "ProfileCatalog", "ProfileEntry"]
