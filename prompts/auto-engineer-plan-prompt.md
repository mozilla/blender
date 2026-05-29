# BLEnder: Auto-Engineer — Plan Phase

## Issue

- **Issue:** #{{ISSUE_NUMBER}}: {{ISSUE_TITLE}}

{{ISSUE_BODY}}

{{ISSUE_COMMENTS}}

## Repo structure

```
{{REPO_TREE}}
```

## Your task

Read the issue and explore the codebase. Produce a detailed implementation
plan. Be specific about which files to change, what to add, and how to
test the changes.

**You have a limited turn budget. Be efficient. Your final response
must include the plan — that is the only deliverable that matters.**

### Step 1: Understand the issue

Read the issue description and comments. Identify the core problem and
any constraints mentioned by maintainers.

### Step 2: Explore the codebase

Read the relevant source files. Understand the existing patterns,
conventions, and architecture. Check for tests, configs, and docs that
relate to the issue.

### Step 3: Write the plan

Produce a structured plan covering:
- **Summary:** one paragraph explaining the approach
- **Files to Change:** list each file with a description of changes
- **Implementation Steps:** ordered steps to follow
- **Test Strategy:** how to verify the changes work
- **Risks:** anything that could go wrong or needs human judgment

### Step 4: Output the plan

Your final response MUST include the plan as a fenced block labeled
`PLAN_MD`. Do not write any files. Just output this block:

````
```PLAN_MD
# Plan: <issue title>

## Summary

<one paragraph>

## Files to Change

- `path/to/file.py` — <description>

## Implementation Steps

1. <step>

## Test Strategy

- <how to test>

## Risks

- <risk>
```
````

## Rules

- Do NOT edit or create any files. Read and analyze only.
- Do NOT run `git` commands.
- Your final response MUST include the ```PLAN_MD``` block.
- If addressing plan feedback, incorporate reviewer comments into a revised plan.
