# Architecture

## Responsibility and dependency direction

`orbit-nosql-mongo` adapts MongoDB to the `orbit-nosql` capability and the shared
`orbit-data.Repository` contract. It owns PyMongo client configuration, Mongo collection access,
document mapping, provider error handling, and client cleanup. It does not own application schemas,
business transactions, or MongoDB deployment topology.

```text
Application modules -> orbit-data -> orbit-nosql -> orbit-nosql-mongo -> PyMongo Async -> MongoDB
                            ^              ^
                      shared repository  provider-neutral NoSQL contract
```

Core is optional and is used only for the application resource lifecycle. `orbit-data` and
`orbit-nosql` do not import PyMongo. Applications can instantiate `MongoDatabase` directly without
installing Core. `MongoPlugin` lives in the plugin submodule and the optional `core` extra adds its
Core dependency, keeping Core outside the adapter's base dependency graph.

## Resource lifecycle

Creating the plugin and registering its resource performs no network I/O. The container creates
`AsyncMongoClient` on first resolution, checks connectivity with `ping`, and yields a
`MongoDatabase` that owns both the selected database handle and client. Core calls the resource
cleanup when the application stops. Direct users must call `MongoDatabase.aclose()` themselves.
Cleanup is shared by concurrent callers, and caller cancellation does not interrupt client close.

The plugin is lazy; successful application startup alone does not prove MongoDB is reachable. To
make database connectivity part of readiness, resolve the resource during the application's startup
or readiness hook and treat resolution failure as startup/readiness failure.

## Document mapping and repository behavior

`MongoDatabase.repository(collection, model, key_field="id")` creates a typed
`MongoRepository`. The selected model field maps to MongoDB's `_id`; other fields use their simple
Pydantic serialization and validation aliases. Ambiguous aliases and complex alias paths are
rejected when the repository is constructed. A null or missing key cannot be inserted.

The repository supports `get`, `list`, `add`, `update`, and `delete`:

- `get` reads by `_id` and validates the returned document as the model.
- `list` sorts by `_id` and materializes at most the caller's limit (1–10,000; default 100).
- `add` inserts and maps duplicate-key errors to `RepositoryConflictError`.
- `update` replaces an existing document without upsert and reports whether it matched.
- `delete` reports whether a document existed.

Driver errors are translated to sanitized `MongoOperationError` instances. Invalid stored model
data raises `MongoDocumentError`; it is not silently repaired or returned as an untyped mapping.
Each repository method is one MongoDB operation. This adapter does not implement
`orbit_data.UnitOfWork` or multi-document transactions. Mongo transactions require a supported
replica-set or sharded deployment and a future explicit session contract.

## Source layout

- `src/orbit_nosql_mongo/config.py` validates URI, database, selection timeout, and client pool size.
- `src/orbit_nosql_mongo/plugin.py` registers the lazy Core-owned resource.
- `src/orbit_nosql_mongo/database.py` owns the client and creates typed repositories.
- `src/orbit_nosql_mongo/repository.py` maps Pydantic models to bounded Mongo CRUD operations.
- `tests/test_mongo.py` checks repository semantics and lifecycle with fakes.
- `tests/test_mongo_integration.py` provides an opt-in service test; it is not a substitute for
  replica-set, TLS, failover, or deployment validation.

## Declared runtime dependencies

The package's base dependencies are `orbit-data`, `orbit-nosql`, and `pymongo`. The `core` extra
adds `orbit-core` for lifecycle integration. Test and lint tools are development dependencies, not
runtime dependencies.
