# InfluxDB And Time-Series Queries

- Identify the InfluxDB product and version first, then identify InfluxQL, Flux, or SQL. Do not mix language or version guidance.
- Establish bucket or database, retention, measurement or table shape, tag/field design, timestamp precision, and expected time range.
- Require a bounded time predicate for interactive or recurring queries unless full-history scanning is intentional.
- Check tag cardinality, high-cardinality dimensions, field-versus-tag choices, grouping dimensions, window size, and returned series count.
- Review aggregation order, fill behavior, late or duplicate points, timezone boundaries, downsampling, retention, and task scheduling.
- Avoid relational index advice. Optimize through schema shape, time bounds, partitioning or shard behavior, pre-aggregation, and cardinality control appropriate to the identified version.
- Treat broad deletes, retention changes, and schema migrations as destructive operations requiring explicit confirmation.
- For other NoSQL systems, first identify the data model, partition key, consistency model, query API, indexes, and operational limits; do not assume relational semantics.
