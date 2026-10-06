# Orbit NoSQL Mongo: architecture and boundaries

## Responsibility

`orbit-nosql-mongo` is the MongoDB provider adapter for the `orbit-nosql` capability and shared
`orbit-data.Repository` contract. It uses PyMongo's native asyncio API and provides an optional
Core plugin that owns the async client through the application container. Core, `orbit-data`, and
`orbit-nosql` do not depend on PyMongo.

```bash
python -m pip install orbit-core orbit-data orbit-nosql orbit-nosql-mongo
```

## Declared dependencies

The following dependency declarations come from the checked-in manifests. Optional groups and development dependencies are called out separately.

### `pyproject.toml`
- `orbit-core>=0.1.0a1,<0.2`
- `orbit-data>=0.1.0a1,<0.2`
- `orbit-nosql>=0.1.0a1,<0.2`
- `pymongo>=4.9,<5`
- Optional `dev` group: `pytest>=8,<10`, `pytest-asyncio>=0.24,<2`, `ruff>=0.8,<1`, `mypy>=1.13,<2`.

Declared dependencies do not mean that optional providers or services are bundled with this package.

## Implementation layout

Representative implementation files in this checkout:

- `.tox/wheel-install-current/orbit_nosql_mongo/__init__.py`
- `.tox/wheel-install-current/orbit_nosql_mongo/config.py`
- `.tox/wheel-install-current/orbit_nosql_mongo/plugin.py`
- `.tox/wheel-install-current/orbit_nosql_mongo/repository.py`
- `.tox/wheel-install-final/orbit_nosql_mongo/__init__.py`
- `.tox/wheel-install-final/orbit_nosql_mongo/config.py`
- `.tox/wheel-install-final/orbit_nosql_mongo/plugin.py`
- `.tox/wheel-install-final/orbit_nosql_mongo/repository.py`
- `.tox/wheel-install-verified/orbit_nosql_mongo/__init__.py`
- `.tox/wheel-install-verified/orbit_nosql_mongo/config.py`
- `.tox/wheel-install-verified/orbit_nosql_mongo/plugin.py`
- `.tox/wheel-install-verified/orbit_nosql_mongo/repository.py`
- `src/orbit_nosql_mongo/__init__.py`
- `src/orbit_nosql_mongo/config.py`
- `src/orbit_nosql_mongo/database.py`
- `src/orbit_nosql_mongo/plugin.py`
- `src/orbit_nosql_mongo/repository.py`

## Public contract and scope

## Repository adapter

The resolved resource implements `orbit_nosql.NoSQLDatabase`; it binds typed repositories to named
collections and owns the driver database and client lifecycle. `MongoRepository` implements
`orbit_data.Repository` for a Pydantic model and an async collection.
The model's `id` field maps to MongoDB's `_id` field by default; `key_field` selects another model
field. `get`, `list`, `add`, `update`, and `delete` follow the repository contract. Lists are
bounded, sorted by `_id`, and return detached validated models. Duplicate `_id` writes raise the
provider-neutral `RepositoryConflictError`; provider and model-validation errors are sanitized.

```python
from pydantic import BaseModel

from orbit_nosql_mongo import MongoRepository, MONGO_DATABASE_KEY


class Order(BaseModel):
    id: str
    status: str


database = await application.container.aresolve(MONGO_DATABASE_KEY)
orders = database.repository("orders", Order)
await orders.add(Order(id="order-1", status="new"))
```

This adapter currently provides per-operation repository methods, not `orbit_data.UnitOfWork`.
MongoDB multi-document transactions require a deployment that supports sessions and transactions;
this package does not imply transaction support for standalone servers. The opt-in integration test
uses `ORBIT_MONGO_URI` to exercise the Core plugin, connection ping, repository CRUD/list, and
application-owned client cleanup against a disposable MongoDB server. It does not test replica-set
transactions, authentication, TLS, failover, or production topology.

## Boundary rules

Keep provider SDKs, credentials, transports, and provider-specific error translation in provider adapters. Keep reusable capability contracts in the matching capability package and lifecycle orchestration in Core. Apply the relevant layer for this repository and preserve the dependency direction shown above.
