"""Opt-in live MongoDB integration check; set ORBIT_MONGO_URI to enable it."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from orbit import Application, ApplicationConfig
from pydantic import BaseModel

from orbit_nosql_mongo import MongoConfig
from orbit_nosql_mongo.plugin import MONGO_DATABASE_KEY, MongoPlugin


class _IntegrationDocument(BaseModel):
    """Minimal typed entity for end-to-end repository calls."""

    id: str
    value: str


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("ORBIT_MONGO_URI"), reason="ORBIT_MONGO_URI is not set")
async def test_live_mongo_plugin_repository_crud_and_lifecycle() -> None:
    """Exercise connection ping, bounded repository operations, and Core-owned client cleanup."""
    application = Application(ApplicationConfig(name="mongo-integration"))
    application.plugins.register(
        MongoPlugin(MongoConfig(uri=os.environ["ORBIT_MONGO_URI"], database="orbit_integration"))
    )
    await application.startup()
    collection_name = "items_" + uuid4().hex
    database = None
    try:
        database = await application.container.aresolve(MONGO_DATABASE_KEY)
        repository = database.repository(collection_name, _IntegrationDocument)
        document = _IntegrationDocument(id="integration-item", value="created")
        await repository.add(document)
        assert await repository.get(document.id) == document
        assert await repository.list(limit=10) == (document,)
        updated = document.model_copy(update={"value": "updated"})
        assert await repository.update(updated) is True
        assert await repository.get(document.id) == updated
        assert await repository.delete(document.id) is True
        assert await repository.delete(document.id) is False
    finally:
        try:
            if database is not None:
                await database.driver_database[collection_name].drop()
        finally:
            await application.stop()
