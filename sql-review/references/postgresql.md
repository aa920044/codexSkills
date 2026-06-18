# PostgreSQL

- Confirm the major version and enabled extensions before relying on planner, JSON, or indexing behavior.
- Use `EXPLAIN (ANALYZE, BUFFERS)` only in a safe environment because it executes the statement.
- Compare estimates with actual rows; inspect sequential scans, join strategies, loops, sorts, memory use, and cache effects.
- Check operator/type compatibility and implicit or explicit casts that prevent useful index access.
- Evaluate B-tree, partial, expression, GIN, GiST, and BRIN indexes according to operators, selectivity, table shape, and write cost.
- Review MVCC effects, long transactions, vacuum/analyze health, table or index bloat, lock scope, and deadlock ordering.
- Check JSONB predicates, array operations, CTE use, keyset pagination, NULL ordering, and timezone semantics.
- Avoid disabling planner methods or adding hints as a routine fix.
