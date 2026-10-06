# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Core plugin that lazily owns one PyMongo async client and database resource."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from orbit import Application
from orbit.plugins import Plugin, PluginMetadata
from pymongo import AsyncMongoClient

from orbit_nosql_mongo.config import MongoConfig
from orbit_nosql_mongo.database import MongoDatabase, _close_client

MONGO_DATABASE_KEY = "orbit.mongo.database"
"""Container key for the configured NoSQL database resource."""


class MongoPlugin(Plugin):
    """Register a MongoDB database as a lazy, Core-owned application resource."""

    metadata = PluginMetadata(
        name="orbit-nosql-mongo",
        version="0.1.0a1",
        capabilities=frozenset({"database.document.mongodb"}),
    )

    def __init__(self, config: MongoConfig) -> None:
        """Capture validated settings without opening a network connection."""
        if not isinstance(config, MongoConfig):
            raise TypeError("MongoPlugin requires MongoConfig.")
        self._config = config

    def setup(self, application: Application) -> None:
        """Register the database resource without connecting during composition."""
        if not isinstance(application, Application):
            raise TypeError("MongoPlugin requires an Orbit Application.")
        application.container.register_resource(
            MONGO_DATABASE_KEY, lambda _: self._managed_database()
        )

    @asynccontextmanager
    async def _managed_database(self) -> AsyncIterator[MongoDatabase]:
        """Ping on first resolution, yield a NoSQL resource, then close its owning client."""
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
            self._config.uri.get_secret_value(),
            serverSelectionTimeoutMS=self._config.server_selection_timeout_ms,
            maxPoolSize=self._config.max_pool_size,
        )
        resource: MongoDatabase | None = None
        try:
            await client.admin.command("ping")
            resource = MongoDatabase(client[self._config.database], client)
            yield resource
        finally:
            if resource is None:
                await _close_client(client)
            else:
                await resource.aclose()


__all__ = ["MONGO_DATABASE_KEY", "MongoPlugin"]
