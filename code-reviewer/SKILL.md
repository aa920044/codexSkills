---
name: code-reviewer
description: Review changed files, pull requests, diffs, branches, or pasted code for correctness bugs, security vulnerabilities, performance problems, maintainability risks, and architectural issues. Use when the user asks for a code review, PR review, diff review, merge readiness assessment, or actionable feedback on code quality and best practices.
---

# Code Reviewer

Perform a focused, actionable review at senior-engineer depth. Prioritize issues that can affect users or future changes; skip noise.

## Workflow

1. Identify the review target:
   - Review explicitly named files when provided.
   - In a Git repository with uncommitted changes, inspect `git diff` and `git diff --staged`.
   - For a feature branch, compare it with the appropriate base branch, such as `git diff main...HEAD`.
   - Review pasted code directly.
   - For large diffs, prioritize new files, changed logic, configuration, then formatting-only changes.
2. Read enough surrounding code, tests, and established conventions to assess behavior accurately.
3. Check five dimensions:
   - Correctness: edge cases, null access, races, missing error handling, incorrect conditions, type errors, and broken contracts.
   - Security: injection, traversal, secrets, insufficient validation, insecure defaults, authorization gaps, and sensitive logging.
   - Performance: N+1 work, unbounded processing, blocking operations, unnecessary renders, missing pagination, and avoidable allocations.
   - Maintainability: duplicated or overly broad logic, unclear names, swallowed errors, dead code, and missing tests for risky behavior.
   - Architecture: violations of local patterns, misplaced business logic, tight coupling, and unjustified or missing abstractions.
4. Verify suspected findings against the actual execution path. Do not report speculative problems as facts.
5. Choose validation commands conservatively:
   - For a Wap project, do not run any command that builds, compiles, packages, or starts either the frontend or backend.
   - Also skip tests, checks, or scripts that trigger frontend or backend compilation as a prerequisite or side effect.
   - Limit Wap project validation to code inspection and non-compiling static checks, such as linting, only when their configuration confirms they do not compile the project.
   - For other projects, run relevant focused tests or static checks when feasible.
   - State all validation gaps caused by skipped compilation or tests.

## Review Format

Lead with findings ordered by severity. Use exact file and line references. For each finding, explain the failure scenario and impact, then give a concise fix; include corrected code only when it materially clarifies the change.

Use these severity levels:

- **Critical (must fix before merge):** production bugs, security vulnerabilities, data loss, or serious regressions.
- **Suggestions (should fix):** meaningful reliability, performance, maintainability, testing, or developer-experience issues.
- **Nitpicks (optional):** at most three high-value style or naming improvements.

After findings, include open questions or assumptions when needed, followed by a brief review summary and one or two specific strengths. If there are no findings, say so clearly and mention remaining test gaps or residual risk.

## Rules

- Follow the repository's established style and architecture.
- Do not request comments for self-explanatory code.
- Do not inflate severity or pad the review with filler.
- Distinguish confirmed defects from questions and assumptions.
- Focus on changed behavior, but report surrounding code only when the change exposes or worsens an existing issue.
- Prefer a short review with real findings over a long list of weak observations.
