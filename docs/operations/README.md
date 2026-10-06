# Orbit NoSQL Mongo: operations and security

This guide organizes runtime behavior documented by the package. It does not certify production readiness. Verify provider/client versions, permissions, transport security, limits, and failure behavior in the target environment before release.

## Configuration surface

Environment names found in the package README:

- `ORBIT_MONGO_URI`

Use the package README's constructor and deployment examples. Store credentials in a secret manager and avoid logging credentials, raw provider errors, request data, or opaque cursors.

## Lifecycle, failure behavior, and limits

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

## Production validation

Validate startup/shutdown cleanup, timeout and cancellation behavior, concurrency and payload bounds where applicable, secret rotation and least-privilege access, data durability, backup/restore, and failover against the selected provider. Do not infer distributed or durable guarantees from an in-process API or fake-client tests.
