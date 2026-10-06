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
"""Typed MongoDB CRUD adapter implementing Orbit's provider-neutral repository contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, Protocol, TypeVar

from bson.errors import InvalidDocument
from orbit_data import Repository, RepositoryConflictError
from pydantic import BaseModel, ValidationError
from pymongo.errors import DuplicateKeyError, PyMongoError

EntityT = TypeVar("EntityT", bound=BaseModel)
KeyT = TypeVar("KeyT", contravariant=True)
MongoDocument = dict[str, Any]


def _affected(count: object, operation: str) -> bool:
    """Validate provider write metadata before returning the repository boolean result."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise MongoOperationError(operation)
    return count > 0


class MongoCursor(Protocol):
    """Small async cursor surface used by the repository and test doubles."""

    def sort(self, key_or_list: Any, direction: int = 1) -> MongoCursor:
        """Sort documents before applying the requested page bound."""

    def limit(self, limit: int) -> MongoCursor:
        """Limit the number of documents returned by the cursor."""

    async def to_list(self, length: int | None = None) -> list[Mapping[str, Any]]:
        """Materialize at most the requested number of documents asynchronously."""


class MongoCollection(Protocol):
    """Minimal asynchronous collection operations required by `MongoRepository`."""

    async def find_one(self, filter: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Find one document matching the filter."""

    def find(self, filter: Mapping[str, Any]) -> MongoCursor:
        """Return an asynchronous cursor for documents matching the filter."""

    async def insert_one(self, document: Mapping[str, Any]) -> Any:
        """Insert a document and return the driver's write result."""

    async def replace_one(
        self, filter: Mapping[str, Any], replacement: Mapping[str, Any], *, upsert: bool = False
    ) -> Any:
        """Replace one matching document and return the driver's write result."""

    async def delete_one(self, filter: Mapping[str, Any]) -> Any:
        """Delete one matching document and return the driver's write result."""


class MongoDocumentError(Exception):
    """Raised when a stored or submitted document cannot satisfy its Pydantic model."""


class MongoOperationError(Exception):
    """Sanitized failure from a MongoDB operation; driver details are not exposed."""

    def __init__(self, operation: str) -> None:
        """Identify the failed operation without copying driver error text or credentials."""
        self.operation = operation
        super().__init__(f"MongoDB {operation} operation failed.")


class MongoRepository(Repository[EntityT, KeyT], Generic[EntityT, KeyT]):
    """Implement bounded CRUD for one Pydantic model and MongoDB collection.

    The configured model field is mapped to MongoDB's reserved ``_id`` field. Other model fields
    honor simple Pydantic serialization and validation aliases. Complex alias paths are rejected so
    the mapping remains explicit and deterministic.
    """

    def __init__(
        self,
        collection: MongoCollection,
        model: type[EntityT],
        *,
        key_field: str = "id",
    ) -> None:
        """Bind a typed Pydantic entity to a collection and its application-defined key field."""
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise TypeError("model must be a Pydantic BaseModel class.")
        if not isinstance(key_field, str) or key_field not in model.model_fields:
            raise ValueError("key_field must name a field on the Pydantic model.")

        storage_names: dict[str, str] = {}
        validation_names: dict[str, str] = {}
        for field_name, field in model.model_fields.items():
            storage_name = field.serialization_alias or field.alias or field_name
            validation_name = field.validation_alias
            if validation_name is None:
                validation_name = field.alias or field_name
            if not isinstance(storage_name, str) or not isinstance(validation_name, str):
                raise ValueError("Mongo model fields require simple string aliases.")
            if field_name != key_field and storage_name == "_id":
                raise ValueError("Only the configured key field may map to MongoDB's '_id'.")
            storage_names[field_name] = storage_name
            validation_names[field_name] = validation_name
        if len(set(storage_names.values())) != len(storage_names):
            raise ValueError("Pydantic serialization aliases must be unique for Mongo documents.")
        if len(set(validation_names.values())) != len(validation_names):
            raise ValueError("Pydantic validation aliases must be unique for Mongo documents.")

        self._collection = collection
        self._model = model
        self._key_field = key_field
        self._storage_names = storage_names
        self._validation_names = validation_names

    @property
    def model(self) -> type[EntityT]:
        """Return the Pydantic entity model associated with this repository."""
        return self._model

    async def get(self, key: KeyT) -> EntityT | None:
        """Fetch one model by `_id`, returning `None` if it is absent."""
        try:
            document = await self._collection.find_one({"_id": key})
        except PyMongoError:
            raise MongoOperationError("read") from None
        return None if document is None else self._decode(document)

    async def list(self, *, limit: int = 100) -> tuple[EntityT, ...]:
        """Return a stable `_id`-ordered page bounded to at most 10,000 documents."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise ValueError("Mongo repository list limit must be between 1 and 10,000.")
        try:
            cursor = self._collection.find({}).sort("_id", 1).limit(limit)
            documents = await cursor.to_list(length=limit)
        except PyMongoError:
            raise MongoOperationError("list") from None
        return tuple(self._decode(document) for document in documents)

    async def add(self, entity: EntityT) -> None:
        """Insert one model, mapping duplicate `_id` errors to the provider-neutral conflict."""
        document = self._encode(entity)
        try:
            await self._collection.insert_one(document)
        except DuplicateKeyError:
            raise RepositoryConflictError() from None
        except (PyMongoError, InvalidDocument):
            raise MongoOperationError("insert") from None

    async def update(self, entity: EntityT) -> bool:
        """Replace one model by `_id`, returning whether an existing document was matched."""
        document = self._encode(entity)
        key = document["_id"]
        try:
            result = await self._collection.replace_one({"_id": key}, document, upsert=False)
        except DuplicateKeyError:
            raise RepositoryConflictError() from None
        except (PyMongoError, InvalidDocument):
            raise MongoOperationError("update") from None
        return _affected(result.matched_count, "update")

    async def delete(self, key: KeyT) -> bool:
        """Delete one document by `_id` and report whether it existed."""
        try:
            result = await self._collection.delete_one({"_id": key})
        except PyMongoError:
            raise MongoOperationError("delete") from None
        return _affected(result.deleted_count, "delete")

    def _encode(self, entity: EntityT) -> MongoDocument:
        """Serialize a validated model into BSON fields, moving its key to Mongo `_id`."""
        if not isinstance(entity, self._model):
            raise MongoDocumentError("Entity does not match this repository's model.")
        try:
            values = entity.model_dump(mode="python", by_alias=True)
        except (TypeError, ValueError):
            raise MongoDocumentError("Entity could not be serialized for MongoDB.") from None
        key_name = self._storage_names[self._key_field]
        if key_name not in values:
            raise MongoDocumentError("Entity is missing its configured key field.")
        key = values.pop(key_name)
        if key is None:
            raise MongoDocumentError("Entity key must not be null.")
        values["_id"] = key
        return values

    def _decode(self, document: Mapping[str, Any]) -> EntityT:
        """Validate a detached Mongo document and map `_id` back to its model key field."""
        if "_id" not in document:
            raise MongoDocumentError("Mongo document is missing its '_id' key.")
        values: dict[str, Any] = {}
        for field_name, storage_name in self._storage_names.items():
            document_name = "_id" if field_name == self._key_field else storage_name
            if document_name in document:
                values[self._validation_names[field_name]] = document[document_name]
        try:
            return self._model.model_validate(values)
        except ValidationError:
            raise MongoDocumentError(
                "Stored Mongo document does not match its Pydantic model."
            ) from None


__all__ = [
    "MongoCollection",
    "MongoCursor",
    "MongoDocumentError",
    "MongoOperationError",
    "MongoRepository",
]
