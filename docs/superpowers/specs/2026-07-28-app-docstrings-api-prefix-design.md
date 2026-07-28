# App Docstrings and API Prefix Design

## Goal

Make the responsibilities of every class and function under `app/` immediately
understandable in an IDE, and simplify the knowledge query endpoint from
`POST /api/v1/query` to `POST /api/query`.

## Docstring Scope

Add an English docstring to every class, function, and method under `app/`,
including private helpers, validators, protocol methods, properties, context
manager methods, and nested functions. Each docstring will use two or three
concise lines to explain the callable's purpose, role, and essential logic.

Docstrings will describe behavior that is not already obvious from the
signature. They will not restate parameter names line by line, introduce new
documentation tooling, or change runtime behavior.

## API Prefix

Change the knowledge controller router prefix from `/api/v1` to `/api`. The
resulting query endpoint will be `POST /api/query`; no compatibility alias for
`POST /api/v1/query` will be retained.

Update the active README examples and query API integration tests to use the
new path. Historical plans, specifications, and the project blueprint will
remain unchanged because they record the contracts that existed when those
documents were written.

## Validation

Run Ruff against `app/` and the affected test file, then run the unit test suite
and the query API integration tests. Verify that every class and callable
defined under `app/` has a non-empty docstring and that no active application,
README, or test reference still uses `/api/v1/query`.
