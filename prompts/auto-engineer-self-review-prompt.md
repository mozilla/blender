# BLEnder: Auto-Engineer — Self-Review

## Original plan

{{PLAN_CONTENT}}

## Merged PR diff

```diff
{{PR_DIFF}}
```

## Your task

Compare the final merged diff against the original plan. Write a summary
for the team. Be honest about deviations.

**You have a limited turn budget. Be efficient. Your final response
must include the summary — that is the only deliverable that matters.**

### What to cover

1. **What was implemented as planned** — brief confirmation
2. **What changed from the plan** — anything done differently and why
3. **What was added beyond the plan** — extra changes not in the plan
4. **What was dropped** — planned changes that were not implemented
5. **Test coverage** — were the planned tests written?

### Output

Your final response MUST include the summary as a fenced block labeled
`SELF_REVIEW_MD`:

````
```SELF_REVIEW_MD
## Self-Review

### Implemented as planned
- <item>

### Changed from plan
- <item>

### Added beyond plan
- <item>

### Dropped
- <item>

### Test coverage
- <item>
```
````

## Rules

- Do NOT edit or create any files. Read and analyze only.
- Do NOT run `git` commands.
- Your final response MUST include the ```SELF_REVIEW_MD``` block.
