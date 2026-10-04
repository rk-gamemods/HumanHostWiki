# Unofficial Game Data Wiki for Human Host

An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio.

Local umbrella for a public, English, free, ad-free player and modding reference.
It defines one navigation hub and twelve topic repositories, with versioned
factual catalogs and unattended updates.

Start with the [document and contract index](docs/README.md). It identifies the
owner of each rule, procedure and evidence record. The
[accepted ADR](docs/adr/0001-versioned-public-wiki.md) records product decisions.

- [Repository and relationship map](docs/REPOSITORIES.md), generated from
  [project.json](project.json).
- [Commands and recovery](docs/WORKFLOW.md).
- [Input snapshot receipts](snapshots/README.md).
- [Coordinated release contract](releases/README.md).

## Status and setup

Open the [public reader](https://rk-gamemods.github.io/HumanHost-Wiki/).
The [delivery acceptance inventory](docs/ACCEPTANCE.md) owns current status,
captured-build evidence and verification limits. Follow
[commands and recovery](docs/WORKFLOW.md) to update locally, then the separate
[publication gate](docs/PUBLICATION.md#production-gate) to publish a chosen release.

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
py -3 tools/run_tests.py --changed main
```

The build command prints the absolute preview entry path. The ADR is the owning
decision record; generated navigation and maps are derived from the registry.
