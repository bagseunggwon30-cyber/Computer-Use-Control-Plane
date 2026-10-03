# Commands

Use `cucp --help` or `python pcucp-next/python/run_source.py --help`. CLI: version, doctor, windows, uia-tree, ocr-image, ocr-find-text, find-label, plan, task-plan, workflow-plan/run, task-build/run, form-plan/run, mcp and serve.

JSONL/MCP commands and schemas come from `capabilities` and pcucp-next/schemas/request.schema.json. Inputs require startup live permission and fresh single-use observation/element references. A routing/task plan is not permission or proof of execution.

A read-only workflow: `{"steps":[{"command":"windows","args":{}}]}`. Preview `cucp workflow-plan --file plans/observe-windows.json --json`; run `cucp workflow-run --file plans/observe-windows.json --json`. --dry-run returns a plan. Maximum 64 workflow leaves/12 batch steps; arbitrary scripts and old command-string macros are rejected.

CDP needs an explicit startup endpoint; read commands do not evaluate JS and cdp-eval requires live permission. Old macro/legacy entries are retired; see [migration](../docs/migration-matrix.md).
