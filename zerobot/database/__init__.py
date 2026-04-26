"""Persistence layer: async SQLAlchemy engine, ORM models, and services.

Importing this package has the side effect of registering every ORM table on
``Base.metadata``, which the bootstrap script (``zerobot.main``) relies on
when calling ``Base.metadata.create_all``.
"""

from zerobot.database import models, port_registry  # noqa: F401  - register tables

__all__ = ["models", "port_registry"]
