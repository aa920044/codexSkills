---
name: sql-review
description: Review SQL, database schemas, indexes, query plans, migrations, ORM-generated queries, and time-series queries for correctness, security, performance, concurrency, and maintainability. Use for Microsoft SQL Server, MySQL, Oracle Database, PostgreSQL, InfluxDB, JPA native queries, query optimization, N+1 analysis, indexing advice, and database-specific rewrites.
---

# SQL Review

Review database code with production impact in mind. Prefer evidence from schema, indexes, row counts, execution plans, and database versions over generic tuning advice.

## Workflow

1. Identify the engine, version, query language, and execution context. Infer them from repository configuration when possible; state assumptions when unknown.
2. Read the relevant reference:
   - SQL Server: [mssql.md](references/mssql.md)
   - MySQL: [mysql.md](references/mysql.md)
   - Oracle: [oracle.md](references/oracle.md)
   - PostgreSQL: [postgresql.md](references/postgresql.md)
   - InfluxDB: [influxdb.md](references/influxdb.md)
3. Establish the data shape: tables or measurements, keys, relationships, indexes, estimated cardinality, selectivity, retention, and expected result semantics.
4. Review these dimensions:
   - Correctness: joins, predicates, NULL semantics, duplicates, aggregation, ordering, pagination, date boundaries, time zones, and type conversions.
   - Security: parameterization, dynamic identifiers, injection, permissions, tenant isolation, row-level access, and sensitive data exposure.
   - Performance: access paths, SARGability, index fit, join strategy, cardinality estimates, scans, sorts, spills, N+1 queries, excessive result sets, and unnecessary work.
   - Concurrency: transaction boundaries, isolation, locks, deadlocks, lost updates, idempotency, and long-running statements.
   - Maintainability: dialect coupling, brittle hints, duplicated query logic, unclear aliases, migration safety, and ORM/query contract mismatches.
5. Ask for an actual plan, schema, index definition, parameters, or row counts only when it would materially change the conclusion. Continue with clearly labeled assumptions otherwise.
6. Do not execute SQL against a database or recommend production changes without explicit authorization. Remember that execution-plan commands such as `EXPLAIN ANALYZE` may run the statement.

## Output

Lead with confirmed findings ordered by severity. For each finding, include the query or file location, failure scenario, impact, and a database-appropriate fix. Show a rewritten query when useful, but do not claim it is faster without plan or workload evidence.

Then include:

- **Questions / assumptions:** only facts needed to firm up the review.
- **Suggested validation:** safe plan, statistics, or representative test steps.
- **Summary:** merge readiness and the highest-impact change.

If no material issue is found, say so and identify the remaining uncertainty. Avoid style-only rewrites and cargo-cult index recommendations.

## Rules

- Preserve business semantics before optimizing.
- Treat indexes as workload-level design, not one-index-per-query advice.
- Account for writes, storage, maintenance, and locking costs when proposing indexes.
- Prefer bind parameters for values; validate dynamic table, column, and sort identifiers with allowlists.
- Distinguish estimated plans from actual runtime evidence.
- Do not recommend `NOLOCK`, optimizer hints, forced indexes, or isolation changes without explaining correctness risks.
- Call out ORM behavior such as N+1 loading, generated count queries, pagination, and transaction scope when relevant.
