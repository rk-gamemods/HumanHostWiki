# Unofficial Game Data Wiki for Human Host

This is an independent local Git repository. The parent workspace and the local
decompiled snapshot have separate histories. Start with [README.md](README.md)
and [ADR-0001](docs/adr/0001-versioned-public-wiki.md).

## Owning contracts

- The ADR owns the architecture and accepted product decisions.
- The user-approved public name is `Unofficial Game Data Wiki for Human Host`,
  stored in `project.json`. Public headers state: "An unofficial community
  project. Not affiliated with or endorsed by Virtual Matrix Studio."
  Do not assign a different public brand without the user's choice.
- `project.json` owns repository identities, category ownership, navigation,
  relationships and pipeline dependencies. Update it before derived maps.
- `wikibuild/` owns shared orchestration. Topic repositories own their content;
  they do not fork the orchestrator or reach into each other's working trees.
- `snapshots/` holds small input receipts. `releases/` is reserved for validated
  coordinated release manifests. These are different states.
- `workspace.lock.json` pins the local child checkout baseline. It is not a
  gameplay release manifest. Use `wiki.py lock` only after reviewing child commits.
- `repositories/` contains independent, ignored local repositories. Do not add
  them to this repository as ordinary directories, Git submodules or subtrees.

## Work and publication

The accepted product is a public, English, free, ad-free factual wiki with the
full agreed catalog and historical provenance.
The ADR requires operator-invoked runs that complete supported updates unattended,
including classification, capacity management and release. Report unresolved wiki
exceptions at the end for user direction; report execution failures separately.
Initial delivery has a stricter completion gate: review and reconcile every known
content and article exception, including the extraction rules that caused it.
The user has authorized the entire initial backlog. Do not ask which initial
exceptions to review or treat successful stage execution as a working baseline.
Post-baseline exception reporting applies only after that baseline is established.
The original backlog is reconciled for build 25548639. `docs/ACCEPTANCE.md` is
the closed delivery checklist derived from the ADR, map and operating guide.
Tie further investigation to a listed requirement and a reproducible defect or
missing deterministic check. Optional prose and additional gameplay research are
not completion gates. Unknown verification and unavailable historical evidence
must be reported accurately; they do not authorize an endless research program.
Do not introduce a scheduler, automatic LLM processing or intermediate approvals.
Derived factual documentation belongs in the wiki repositories. The parent
codebase's source and raw catalog remain local inputs, read in place.

Current tooling builds an architecture/navigation preview, registers input snapshots
and extracts selected facts in every topic with durable identity decisions.
`wiki.py reader` projects those records into a validated static reader candidate.
See `docs/ACCEPTANCE.md` for delivery status, `docs/IMPLEMENTATION.md` for historical evidence and
`docs/EXTRACTION.md` for adapter ownership and extension rules. Identity matching,
semantic revisions and recovery are owned by `docs/IDENTITY.md`.
Static rendering, browser behavior and pack ownership are in `docs/READER.md`.
The decompile handoff and local stage runner are implemented in `docs/PIPELINE.md`.
`docs/RELEASE.md` owns coordinated local Git releases. `docs/PUBLICATION.md` owns
GitHub provisioning, topic-first Pages publication and hub rollback. Keep content exceptions separate from
execution failures when reporting a run.
`docs/CAPACITY.md` owns allocation boundaries and recovery.
Never call a registered snapshot a verified wiki release or an empty topic a
completed catalog. Keep implementation status accurate in the workflow document.

Preserve local-only operation until a task authorizes remote setup or publishing.
Do not invent remote existence, deployment URLs or current-game verification.
Use the user-approved subject structure; new game concepts must be accounted for
in technical reference or a reviewed category addition, never silently dropped.

## Validation

```powershell
py -3 wiki.py validate
py -3 wiki.py map --check
py -3 wiki.py check-lock
py -3 -m unittest discover -s tests -v
git diff --check
```

Changes to persistent generation must exercise repeat execution and failure
before promotion. Do not bypass a failed boundary check or overwrite unknown
files. See [workflow](docs/WORKFLOW.md) for local commands and recovery.
