# MySQL

- Confirm the major version, storage engine, SQL mode, charset, and collation before suggesting syntax or behavior changes.
- Use `EXPLAIN` or `EXPLAIN ANALYZE` appropriately; remember that analyze variants execute the statement.
- Check composite indexes using the leftmost-prefix rule, range boundaries, covering opportunities, and redundant indexes.
- Inspect full scans, temporary tables, filesorts, join order, row estimates, and non-SARGable expressions.
- Review InnoDB isolation, gap and next-key locks, deadlocks, transaction length, and consistent lock ordering.
- Check pagination stability, large offsets, collation-driven comparisons, implicit conversions, and timezone handling.
- Avoid treating `FORCE INDEX` as a default fix; require plan and workload evidence.
