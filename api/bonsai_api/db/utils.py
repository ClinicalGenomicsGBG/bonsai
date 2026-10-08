"""Helper functions for setup and teardown of database connections."""

import logging
from contextlib import contextmanager
from typing import Generator

from motor.motor_asyncio import AsyncIOMotorClient

from ..config import settings
from .db import MongoDatabase

LOG = logging.getLogger(__name__)

db = MongoDatabase()


def open_db() -> None:
    """Create the MongoDB client once, when the API starts."""
    db.client = AsyncIOMotorClient(
        settings.mongodb_uri,
        maxPoolSize=settings.max_connections,
        minPoolSize=settings.min_connections,
    )

    db.setup()
    LOG.debug("Setup connection to mongo database")

def close_db() -> None:
    """Close the MongoDB client the API shuts down."""
    db.close()
    LOG.debug("Teardown of database connection")

def get_db() -> Generator[MongoDatabase, None, None]:
    """Return the database connection shared by all requests

    The client is created once (see open_db) and never closed per request:
    closing it here would also close it for every other request in progress.
    """
    if db.client is None:
        open_db()
    yield db


@contextmanager
def get_db_connection() -> Generator[MongoDatabase, None, None]:
    """Set up database connection."""
    db.client = AsyncIOMotorClient(
        settings.mongodb_uri,
        maxPoolSize=settings.max_connections,
        minPoolSize=settings.min_connections,
    )
    try:
        LOG.debug("Setup connection to mongo database")
        db.setup()  # initiate collections
        yield db
    finally:
        # teardown database connection
        db.close()
        LOG.debug("Initiate teardown of database connection")
