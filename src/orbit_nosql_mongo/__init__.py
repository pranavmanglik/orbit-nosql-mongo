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
"""Optional MongoDB adapter for Orbit repositories and application lifecycles."""

from orbit_nosql_mongo.config import MongoConfig
from orbit_nosql_mongo.database import MongoDatabase
from orbit_nosql_mongo.plugin import MONGO_DATABASE_KEY, MongoPlugin
from orbit_nosql_mongo.repository import (
    MongoCollection,
    MongoCursor,
    MongoDocumentError,
    MongoOperationError,
    MongoRepository,
)

__all__ = [
    "MONGO_DATABASE_KEY",
    "MongoCollection",
    "MongoConfig",
    "MongoCursor",
    "MongoDocumentError",
    "MongoDatabase",
    "MongoOperationError",
    "MongoPlugin",
    "MongoRepository",
]
