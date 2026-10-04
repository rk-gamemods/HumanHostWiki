# Unofficial Game Data Wiki for Human Host

This umbrella, its parent workspace and the local capture have separate Git
histories. Start with [README.md](README.md) and the
[document and contract index](docs/README.md). Use that map to find each owner.
For game updates, follow the [HumanHostMods runbook](../docs/RUNBOOK-game-update.md).

## Repository rules

- Keep the user-approved public name in `project.json`. Public headers state:
  "An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio."
  Do not change the public brand without the user's choice.
- Update `project.json` before derived maps. Topic repositories own content;
  `wikibuild/` owns shared orchestration. Do not fork the orchestrator or read
  another topic's mutable checkout.
- Keep input receipts, checkout locks, local releases and publication receipts
  distinct. Use `wiki.py lock` only after reviewing child commits.
- `repositories/` contains independent, ignored repositories. Do not add them
  as ordinary directories, Git submodules or subtrees.
- Read source and raw catalogs in place. Do not add decompiled game code to any
  repository. Derived factual records belong in the wiki repositories.

## Work and publication rules

- Complete supported operator-invoked updates unattended. Report content
  exceptions at the end; report execution failures separately.
- Initial delivery requires review of every known content and article exception,
  including the causing extraction rules. The user authorized the whole initial
  backlog. Do not ask which exceptions to review. Use
  [delivery acceptance](docs/ACCEPTANCE.md) for its disposition and current status.
- Tie further investigation to a listed acceptance requirement and a reproducible
  defect or missing deterministic check. Optional prose and extra gameplay
  research are not completion gates. Report unknown verification accurately.
- Do not introduce a scheduler, automatic LLM processing or intermediate approvals.
- Stop updates after the local release and both retention stages. Publish through
  the separate operator command and honor the full
  [production gate](docs/PUBLICATION.md#production-gate) before provisioning.
  There is no override. Abandon incomplete publication attempts locally before
  a fresh rehearsal and publication; never resume or salvage failed runs.
- Preserve local-only operation until the task authorizes remote setup or publishing.
  Do not invent remote existence, deployment URLs or current-game verification.
- Account for new concepts in technical reference or a reviewed category addition.
  Never silently drop them, call a snapshot a verified release or call an empty
  topic a completed catalog.

## Validation

```powershell
py -3 wiki.py validate
py -3 wiki.py map --check
py -3 wiki.py check-lock
py -3 tools/check_components.py
py -3 tools/run_tests.py --changed main
git diff --check
```

Follow [component isolation](docs/ARCHITECTURE.md#running-tests). Use
`py -3 tools/run_tests.py --all` for main integration. Changes to persistent
generation must exercise repeat execution and failure before promotion.
Do not bypass failed boundaries or overwrite unknown files.
