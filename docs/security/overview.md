# Security

## Connection secrets and transport

`MongoConfig.uri` is a Pydantic `SecretStr`, so model representations redact its value. The plugin
reveals the URI only when constructing `AsyncMongoClient`; applications should load it from a
secret manager or protected runtime configuration and must not log it.

The config validates URI shape but does not require TLS. For remote production clusters, use a
`mongodb+srv://` URI or explicitly set `tls=true` in a standard URI. PyMongo enables TLS by default
for SRV URIs and verifies server certificates when TLS is enabled; the URI can override this, so
review its query options and reject `tls=false`, `tlsInsecure=true`, or
`tlsAllowInvalidCertificates=true`. Do not disable certificate verification to work around
deployment certificate errors. Plaintext transport is appropriate only for isolated local
development. See the official [PyMongo TLS guide](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/security/tls/)
and [connection string options](https://www.mongodb.com/docs/manual/reference/connection-string-options/).

Use a dedicated database identity with only the permissions required by the application. Rotate
credentials through the deployment's secret-management system. The adapter does not implement
credential rotation; recreate the client/resource after changing the configured URI.

## Data handling and errors

Repository operations return Pydantic-validated models and sanitize PyMongo failures through
`MongoOperationError`; validation failures for stored records use `MongoDocumentError`. Application
handlers should avoid logging full documents when they may contain personal, financial, or
credential data. Log a correlation identifier and the sanitized operation context instead.

The adapter does not encrypt application fields, redact values returned to application code, or
enforce tenant isolation. Applications must define field-level handling and include tenant/account
scope in their repository model and access layer where required. MongoDB authorization and network
segmentation remain deployment responsibilities.

## Limits and disclosure

`list()` has a hard page bound of 10,000 documents; its default is 100. This bounds one result
materialization but is not a complete defense against expensive queries because the current contract
does not expose arbitrary filters, projections, or indexes. Add indexes and operational query limits
for the application's access patterns.

The repository supports individual CRUD operations only. It does not promise multi-document
atomicity, transaction isolation, backup, encryption-at-rest, or failover. Validate these properties
against the chosen MongoDB deployment before production use. Report security issues privately using
the repository [security policy](../../SECURITY.md), not in public issues.
