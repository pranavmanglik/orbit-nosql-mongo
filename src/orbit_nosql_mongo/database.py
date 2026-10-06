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
"""MongoDB implementation of Orbit's NoSQL capability."""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from orbit_nosql import NoSQLDatabase
from pydantic import BaseModel

from orbit_nosql_mongo.repository import MongoRepository

EntityT = TypeVar("EntityT", bound=BaseModel)
KeyT = TypeVar("KeyT", contravariant=True)


async def _wait_for_close(task: asyncio.Task[None]) -> None:
    """Finish one client close task before allowing caller cancellation to propagate."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _close_client(client: Any) -> None:
    """Close a client safely when resource construction did not complete."""
    await _wait_for_close(asyncio.create_task(client.close()))


class MongoDatabase(NoSQLDatabase):
    """Own one database handle and client while creating typed collection repositories."""

    def __init__(self, database: Any, client: Any) -> None:
        """Bind the native database handle to the client that owns its connections."""
        if not callable(getattr(database, "__getitem__", None)):
            raise TypeError("database must support Mongo collection lookup.")
        if not callable(getattr(client, "close", None)):
            raise TypeError("client must provide close().")
        self._database = database
        self._client = client
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    @property
    def driver_database(self) -> Any:
        """Expose the native database for explicit provider-specific Mongo operations."""
        self._ensure_open()
        return self._database

    def repository(
        self,
        collection: str,
        model: type[EntityT],
        *,
        key_field: str = "id",
    ) -> MongoRepository[EntityT, KeyT]:
        """Bind a typed orbit-data repository to one validated Mongo collection name."""
        self._ensure_open()
        if (
            not isinstance(collection, str)
            or not collection
            or len(collection.encode("utf-8")) > 120
            or "\x00" in collection
            or collection.startswith("$")
        ):
            raise ValueError("Mongo collection name must be 1-120 UTF-8 bytes and a valid name.")
        return MongoRepository(self._database[collection], model, key_field=key_field)

    async def aclose(self) -> None:
        """Close the owning client once and finish cleanup before propagating cancellation."""
        task = self._close_task
        if task is None:
            self._closed = True
            task = asyncio.create_task(self._client.close())
            self._close_task = task

        await _wait_for_close(task)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Mongo database resource is closed.")


__all__ = ["MongoDatabase"]
