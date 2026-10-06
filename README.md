# Orbit NoSQL Mongo

`orbit-nosql-mongo` is the MongoDB provider adapter for the `orbit-nosql` capability and shared
`orbit-data.Repository` contract. It uses PyMongo's native asyncio API and provides an optional
Core plugin that owns the async client through the application container. Core, `orbit-data`, and
`orbit-nosql` do not depend on PyMongo.

```bash
python -m pip install orbit-core orbit-data orbit-nosql orbit-nosql-mongo
```

## Application lifecycle

Configure credentials outside source control. `MongoConfig` stores the URI as a redacted secret,
and `MongoPlugin` registers a lazy, Core-managed database resource:

```python
from orbit import Application, ApplicationConfig
from orbit_nosql_mongo import MongoConfig, MongoPlugin

application = Application(ApplicationConfig(name="orders"))
application.plugins.register(
    MongoPlugin(MongoConfig(uri="mongodb://localhost:27017", database="orders"))
)
await application.startup()
```

The plugin creates its client only when the `MONGO_DATABASE_KEY` resource is first resolved,
checks connectivity with `ping`, and lets Core close the client during application shutdown. Resolve
the database after startup, when Core has run plugin setup and registered its resource. The
connection is scoped to the application's event loop; do not share it between threads, loops, or
applications. Close completion is shared between concurrent callers and is allowed to finish before
cancellation propagates, so Core shutdown and direct `database.aclose()` calls do not race to close
the same client twice. For deployments, use TLS and a least-privilege database account, and provide
the URI through a secret manager or protected environment configuration.

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

## Documentation

The package-specific guides cover [architecture](docs/architecture/overview.md), [operations and security](docs/operations/README.md), and [development](docs/development/README.md), with [security guidance](docs/security/overview.md). The [documentation index](docs/README.md) links to the full package overview and project policies.

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
ruff check .
mypy
```

To run the live service check, set `ORBIT_MONGO_URI` to a disposable MongoDB deployment and run
`python -m pytest tests/test_mongo_integration.py`.

This package is pre-alpha and its API is not stable. It supports Python 3.11 through 3.14.

Licensed under Apache-2.0.

