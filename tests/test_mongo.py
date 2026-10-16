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
"""Test repository semantics and Core resource lifecycle without a MongoDB server."""

from __future__ import annotations

import asyncio
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bson.errors import InvalidDocument
from orbit import Application, ApplicationConfig
from orbit_data import RepositoryConflictError
from orbit_nosql import NoSQLDatabase
from pydantic import BaseModel, Field, SecretStr
from pymongo.errors import DuplicateKeyError, PyMongoError

from orbit_nosql_mongo import (
    MongoConfig,
    MongoDatabase,
    MongoDocumentError,
    MongoOperationError,
    MongoRepository,
)
from orbit_nosql_mongo import plugin as plugin_module
from orbit_nosql_mongo.plugin import MONGO_DATABASE_KEY, MongoPlugin


def test_core_lifecycle_dependency_is_optional() -> None:
    """The provider adapter does not require Core unless users install its plugin extra."""
    manifest = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert not any(dependency.startswith("orbit-core") for dependency in manifest["dependencies"])
    assert manifest["optional-dependencies"]["core"] == ["orbit-core>=0.1.0a1,<0.2"]


class Note(BaseModel):
    """Example entity for repository contract tests."""

    id: str
    body: str


class FakeCursor:
    """In-memory asynchronous cursor implementing the Mongo adapter's narrow contract."""

    def __init__(self, documents: Sequence[Mapping[str, Any]]) -> None:
        """Capture detached test documents for sorting and bounded reads."""
        self._documents = list(documents)
        self._limit = len(documents)

    def sort(self, key_or_list: Any, direction: int = 1) -> FakeCursor:
        """Sort the fixture by one field using Mongo's ascending test order."""
        field = key_or_list if isinstance(key_or_list, str) else key_or_list[0][0]
        self._documents.sort(key=lambda document: document[field], reverse=direction < 0)
        return self

    def limit(self, limit: int) -> FakeCursor:
        """Remember a hard page bound for the asynchronous materialization."""
        self._limit = limit
        return self

    async def to_list(self, length: int | None = None) -> list[Mapping[str, Any]]:
        """Return detached documents within both cursor and caller bounds."""
        bound = self._limit if length is None else min(self._limit, length)
        return [dict(document) for document in self._documents[:bound]]


class FakeCollection:
    """Minimal fake collection with injectable provider errors."""

    def __init__(self) -> None:
        """Start with no documents and no injected failures."""
        self.documents: dict[Any, dict[str, Any]] = {}
        self.read_error: PyMongoError | None = None
        self.invalid_document = False

    async def find_one(self, filter: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Return one fixture document and optionally simulate a driver outage."""
        if self.read_error is not None:
            raise self.read_error
        document = self.documents.get(filter["_id"])
        return None if document is None else dict(document)

    def find(self, filter: Mapping[str, Any]) -> FakeCursor:
        """Return all fixture documents matching the simple equality filter."""
        documents = [
            document
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in filter.items())
        ]
        return FakeCursor(documents)

    async def insert_one(self, document: Mapping[str, Any]) -> Any:
        """Insert a fixture document or raise the corresponding driver error."""
        if self.invalid_document:
            raise InvalidDocument("private serialization value")
        key = document["_id"]
        if key in self.documents:
            raise DuplicateKeyError("private duplicate key details")
        self.documents[key] = dict(document)
        return SimpleNamespace(inserted_id=key)

    async def replace_one(
        self, filter: Mapping[str, Any], replacement: Mapping[str, Any], *, upsert: bool = False
    ) -> Any:
        """Replace a matching fixture document without implicit upserts."""
        del upsert
        key = filter["_id"]
        if key not in self.documents:
            return SimpleNamespace(matched_count=0)
        self.documents[key] = dict(replacement)
        return SimpleNamespace(matched_count=1)

    async def delete_one(self, filter: Mapping[str, Any]) -> Any:
        """Delete one fixture document and report whether it was present."""
        key = filter["_id"]
        return SimpleNamespace(deleted_count=int(self.documents.pop(key, None) is not None))


@pytest.mark.asyncio
async def test_repository_crud_is_bounded_and_maps_duplicate_keys() -> None:
    """CRUD methods follow the orbit-data contract and return validated detached models."""
    collection = FakeCollection()
    repository: MongoRepository[Note, str] = MongoRepository(collection, Note)
    first = Note(id="b", body="second")
    second = Note(id="a", body="first")

    await repository.add(first)
    await repository.add(second)
    with pytest.raises(RepositoryConflictError):
        await repository.add(first)
    assert await repository.get("b") == first
    assert await repository.get("missing") is None
    assert await repository.list(limit=1) == (second,)
    assert await repository.update(Note(id="b", body="updated"))
    assert await repository.get("b") == Note(id="b", body="updated")
    assert not await repository.update(Note(id="missing", body="absent"))
    assert await repository.delete("a")
    assert not await repository.delete("a")


@pytest.mark.asyncio
async def test_repository_maps_pydantic_aliases_to_mongo_id() -> None:
    """Simple distinct validation and serialization aliases round-trip through `_id`."""

    class AliasedNote(BaseModel):
        """Model whose external validation and storage names differ."""

        identifier: str = Field(validation_alias="external_id", serialization_alias="mongo_id")
        body: str

    collection = FakeCollection()
    repository: MongoRepository[AliasedNote, str] = MongoRepository(
        collection, AliasedNote, key_field="identifier"
    )
    note = AliasedNote.model_validate({"external_id": "note-1", "body": "hello"})

    await repository.add(note)

    assert collection.documents["note-1"] == {"body": "hello", "_id": "note-1"}
    assert await repository.get("note-1") == note


@pytest.mark.asyncio
async def test_repository_sanitizes_provider_and_document_errors() -> None:
    """Driver and model failures do not expose credential, document, or provider details."""
    collection = FakeCollection()
    repository: MongoRepository[Note, str] = MongoRepository(collection, Note)
    collection.read_error = PyMongoError("mongodb://user:password@host/private")

    with pytest.raises(MongoOperationError) as read_error:
        await repository.get("note")
    assert "password" not in str(read_error.value)

    collection.read_error = None
    collection.invalid_document = True
    with pytest.raises(MongoOperationError) as write_error:
        await repository.add(Note(id="note", body="hello"))
    assert "private serialization value" not in str(write_error.value)

    collection.invalid_document = False
    collection.documents["bad"] = {"_id": "bad", "body": 3}
    with pytest.raises(MongoDocumentError, match="does not match"):
        await repository.get("bad")


def test_mongo_config_redacts_uri_and_validates_connection_bounds() -> None:
    """Secrets stay redacted; invalid URI, database, and pool settings fail at config time."""
    config = MongoConfig(
        uri=SecretStr("mongodb://user:password@localhost:27017"),
        database="orbit_test",
    )
    assert "password" not in repr(config)
    assert config.max_pool_size == 100
    with pytest.raises(ValueError, match="mongodb://"):
        MongoConfig(uri=SecretStr("http://localhost"), database="orbit_test")
    with pytest.raises(ValueError, match="database"):
        MongoConfig(uri=SecretStr("mongodb://localhost"), database="bad/name")


@pytest.mark.asyncio
async def test_plugin_lazily_registers_and_closes_client_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core receives a lazy database resource and owns closing its client on container shutdown."""
    collection = FakeCollection()

    class FakeDatabase:
        def __getitem__(self, name: str) -> FakeCollection:
            assert name == "notes"
            return collection

    database = FakeDatabase()

    class FakeAdmin:
        """Provide the driver's startup connectivity probe."""

        async def command(self, name: str) -> dict[str, int]:
            assert name == "ping"
            return {"ok": 1}

    class FakeClient:
        """Track database selection and lifecycle without contacting MongoDB."""

        def __init__(self, uri: str, **options: object) -> None:
            self.uri = uri
            self.options = options
            self.admin = FakeAdmin()
            self.closed = False

        def __getitem__(self, name: str) -> object:
            assert name == "orders"
            return database

        async def close(self) -> None:
            self.closed = True

    created: list[FakeClient] = []

    def create_client(uri: str, **options: object) -> FakeClient:
        client = FakeClient(uri, **options)
        created.append(client)
        return client

    monkeypatch.setattr(plugin_module, "AsyncMongoClient", create_client)
    app = Application(ApplicationConfig(name="mongo-test"))
    plugin = MongoPlugin(MongoConfig(uri=SecretStr("mongodb://localhost:27017"), database="orders"))
    app.plugins.register(plugin)
    assert created == []
    await app.configure()
    assert created == []

    resolved = await app.container.aresolve(MONGO_DATABASE_KEY)
    assert isinstance(resolved, NoSQLDatabase)
    assert isinstance(resolved, MongoDatabase)
    assert resolved.driver_database is database
    assert isinstance(resolved.repository("notes", Note), MongoRepository)
    assert created[0].options == {"serverSelectionTimeoutMS": 5_000, "maxPoolSize": 100}
    assert not created[0].closed

    await app.stop()
    assert created[0].closed


@pytest.mark.asyncio
async def test_plugin_contributes_a_read_only_control_room_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI connection check pings MongoDB and releases its temporary client."""
    calls: list[str] = []

    class FakeAdmin:
        async def command(self, name: str) -> dict[str, int]:
            calls.append(name)
            return {"ok": 1}

    class FakeClient:
        def __init__(self, _uri: str, **_options: object) -> None:
            self.admin = FakeAdmin()
            self.closed = False

        def __getitem__(self, _name: str) -> object:
            class FakeDatabase:
                def __getitem__(self, _collection_name: str) -> object:
                    return object()

            return FakeDatabase()

        async def close(self) -> None:
            self.closed = True

    created: list[FakeClient] = []

    def create_client(uri: str, **options: object) -> FakeClient:
        client = FakeClient(uri, **options)
        created.append(client)
        return client

    monkeypatch.setattr(plugin_module, "AsyncMongoClient", create_client)
    plugin = MongoPlugin(MongoConfig(uri=SecretStr("mongodb://localhost"), database="orders"))

    result = await plugin.control_actions[0].handler({})

    assert calls == ["ping"]
    assert result is not None
    assert result.summary == "MongoDB is reachable."
    assert created[0].closed


@pytest.mark.asyncio
async def test_concurrent_database_close_waiters_share_cleanup() -> None:
    """Every caller waits for one client close before the resource becomes unavailable."""
    entered = asyncio.Event()
    release = asyncio.Event()

    class DatabaseHandle:
        def __getitem__(self, name: str) -> FakeCollection:
            return FakeCollection()

    class Client:
        close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1
            entered.set()
            await release.wait()

    client = Client()
    database = MongoDatabase(DatabaseHandle(), client)
    first = asyncio.create_task(database.aclose())
    await entered.wait()
    second = asyncio.create_task(database.aclose())
    await asyncio.sleep(0)
    assert not first.done()
    assert not second.done()

    release.set()
    await asyncio.gather(first, second)
    assert client.close_calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        database.repository("notes", Note)


@pytest.mark.asyncio
async def test_failed_database_close_can_be_retried() -> None:
    """A failed SDK close remains owned and a later shutdown call retries it."""

    class DatabaseHandle:
        def __getitem__(self, name: str) -> FakeCollection:
            return FakeCollection()

    class Client:
        close_calls = 0
        closed = False

        async def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("temporary driver close failure")
            self.closed = True

    client = Client()
    database = MongoDatabase(DatabaseHandle(), client)
    with pytest.raises(RuntimeError, match="temporary driver close failure"):
        await database.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        database.repository("notes", Note)

    await database.aclose()
    await database.aclose()
    assert client.closed
    assert client.close_calls == 2


@pytest.mark.asyncio
async def test_cancelled_driver_close_can_be_retried() -> None:
    """A driver cancellation is retained as a failed attempt rather than mistaken for success."""

    class DatabaseHandle:
        def __getitem__(self, name: str) -> FakeCollection:
            return FakeCollection()

    class Client:
        close_calls = 0
        closed = False

        async def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise asyncio.CancelledError
            self.closed = True

    client = Client()
    database = MongoDatabase(DatabaseHandle(), client)
    with pytest.raises(asyncio.CancelledError):
        await database.aclose()

    await database.aclose()
    assert client.closed
    assert client.close_calls == 2


@pytest.mark.asyncio
async def test_database_close_finishes_before_propagating_cancellation() -> None:
    """Cancellation of a close caller cannot cancel the owned client cleanup."""
    entered = asyncio.Event()
    release = asyncio.Event()

    class DatabaseHandle:
        def __getitem__(self, name: str) -> FakeCollection:
            return FakeCollection()

    class Client:
        close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1
            entered.set()
            await release.wait()

    client = Client()
    database = MongoDatabase(DatabaseHandle(), client)
    cancelled_waiter = asyncio.create_task(database.aclose())
    await entered.wait()
    cancelled_waiter.cancel()
    await asyncio.sleep(0)
    assert not cancelled_waiter.done()

    another_waiter = asyncio.create_task(database.aclose())
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter
    await another_waiter
    assert client.close_calls == 1
