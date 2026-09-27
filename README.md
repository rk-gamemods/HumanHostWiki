# Human Host Wiki

Local umbrella for a public, English, free, ad-free player and modding reference.
It defines one navigation hub and twelve topic repositories, with versioned
factual catalogs and unattended updates as the target architecture.

Start with the [accepted ADR](docs/adr/0001-versioned-public-wiki.md). It records
the complete decisions, provenance model, historical browsing, ownership,
refresh/release pipeline, failure recovery and delivery sequence.

- [Repository and relationship map](docs/REPOSITORIES.md), generated from
  [project.json](project.json).
- [Commands and recovery](docs/WORKFLOW.md).
- [Input snapshot receipts](snapshots/README.md).
- [Coordinated release contract](releases/README.md).

## Current implementation

The foundation validates and initializes independent local repositories,
registers the existing game catalog without copying it, and builds a linked
architecture preview. The unattended runner, gameplay adapters, historical article
rendering and remote publication are planned in the ADR. No remote is configured
by this tool.

Requires Python 3.11+ and Git. The foundation uses only Python's standard library.

```powershell
py -3 wiki.py validate
py -3 wiki.py status
py -3 wiki.py plan
py -3 wiki.py map --check
py -3 wiki.py check-lock
py -3 wiki.py build
py -3 -m unittest discover -s tests -v
```

The build command prints the absolute preview entry path. The ADR is the owning
decision record; generated navigation and maps are derived from the registry.
