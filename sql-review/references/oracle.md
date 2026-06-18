# Oracle Database

- Confirm the Oracle version and compatibility settings before recommending syntax or optimizer behavior.
- Prefer bind variables while considering skew and bind-sensitive plans. Flag unsafe string-built SQL.
- Use `DBMS_XPLAN` output with runtime statistics when available; distinguish estimates from actual rows.
- Check access paths, join methods, cardinality estimates, partition pruning, sorts, spills, and function-wrapped predicates.
- Consider function-based indexes only when expression matching and workload costs are clear.
- Review sequence or identity semantics, empty-string/NULL behavior, date and timestamp handling, and pagination syntax.
- Treat hints as a last-mile stabilization tool with evidence, not a substitute for statistics, schema, or query fixes.
- Check transaction scope, undo pressure, blocking, and application retry assumptions.
