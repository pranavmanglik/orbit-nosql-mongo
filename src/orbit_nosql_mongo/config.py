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
"""Validated, redacted configuration for the optional MongoDB adapter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class MongoConfig(BaseModel):
    """Connection settings used by the `orbit-nosql-mongo` Core plugin.

    The URI is a secret so model representations and validation output do not disclose credentials.
    TLS and authentication mechanism options belong in the URI or an explicitly configured client.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    uri: SecretStr
    database: str
    server_selection_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    max_pool_size: int = Field(default=100, ge=1, le=10_000)

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: SecretStr) -> SecretStr:
        """Require a bounded MongoDB URI and reject whitespace/control characters."""
        uri = value.get_secret_value()
        if (
            not 1 <= len(uri) <= 4_096
            or not uri.startswith(("mongodb://", "mongodb+srv://"))
            or any(not character.isprintable() or character.isspace() for character in uri)
        ):
            raise ValueError("MongoDB URI must be a bounded mongodb:// or mongodb+srv:// URI.")
        return value

    @field_validator("database")
    @classmethod
    def validate_database(cls, value: str) -> str:
        """Restrict database names to a conservative portable identifier alphabet."""
        if not 1 <= len(value) <= 63 or any(
            not (character.isascii() and (character.isalnum() or character in "_-"))
            for character in value
        ):
            raise ValueError("MongoDB database must be 1–63 ASCII letters, digits, '_' or '-'.")
        return value


__all__ = ["MongoConfig"]
