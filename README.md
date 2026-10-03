# Unofficial Game Data Wiki for Human Host

An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio.

Local umbrella for a public, English, free, ad-free player and modding reference.
It defines one navigation hub and twelve topic repositories, with versioned
factual catalogs and unattended updates.

Start with the [accepted ADR](docs/adr/0001-versioned-public-wiki.md). It records
the complete decisions, provenance model, historical browsing, ownership,
refresh/release pipeline, failure recovery and delivery sequence.

- [Repository and relationship map](docs/REPOSITORIES.md), generated from
  [project.json](project.json).
- [Commands and recovery](docs/WORKFLOW.md).
- [Input snapshot receipts](snapshots/README.md).
- [Coordinated release contract](releases/README.md).

## Current implementation

The [public reader](https://rk-gamemods.github.io/HumanHost-Wiki/) serves selected
facts in every topic with source evidence, search, relationships and capture
selection. The existing decompile command invokes an integrated update that
reuses unchanged work, commits a coordinated release and publishes topic sites
before advancing the hub. Unresolved content is reported after supported work
finishes. See [publication and recovery](docs/PUBLICATION.md).

The [delivery acceptance inventory](docs/ACCEPTANCE.md) records implemented
requirements, finite checks and evidence limitations. The original 193 content
groups and five article issues are reconciled for the current capture. Runtime
verification remains explicitly scoped, and two distinct real catalog builds
are not yet available. Optional gameplay prose is not a completion gate.

Requires Python 3.11+ and Git, plus authenticated GitHub CLI for publication.
Captured C# enum extraction also requires the pinned packages in
`requirements-source.txt`. See [setup and commands](docs/WORKFLOW.md).

```powershell
py -3 wiki.py validate
py -3 wiki.py status
py -3 wiki.py plan
py -3 wiki.py map --check
py -3 wiki.py check-lock
py -3 wiki.py build
py -3 wiki.py extract
py -3 wiki.py update --operator-report
py -3 -m unittest discover -s tests -v
```

The build command prints the absolute preview entry path. The ADR is the owning
decision record; generated navigation and maps are derived from the registry.
