# Microsoft SQL Server

Use this reference first unless the repository clearly targets another engine.

- Inspect actual execution plans when safe, plus `STATISTICS IO` and `STATISTICS TIME` in a representative non-production environment.
- Check implicit conversions, parameter sensitivity, stale statistics, key lookups, spills, residual predicates, and inaccurate cardinality estimates.
- Keep predicates SARGable. Watch functions or arithmetic on indexed columns and mismatched parameter/column types.
- Evaluate clustered, nonclustered, included-column, and filtered indexes against the whole read/write workload.
- Review `OFFSET/FETCH`, window functions, temporary tables, table variables, CTEs, and large `IN` lists for their actual cardinality and plan behavior.
- Treat `NOLOCK` as a correctness tradeoff, not a routine performance fix. Explain dirty, missing, and duplicated-read risks.
- Check transaction duration, lock escalation, deadlock order, snapshot settings, and update conflicts.
- For JPA native SQL, verify named parameters, result mappings, pagination/count queries, SQL Server types, and transaction boundaries.
