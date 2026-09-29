# ADR-0002: Player-facing template and generated guides

**Accepted 2026-09-28.** Amends [ADR-0001](0001-versioned-public-wiki.md) §1, §5 and §7.
ADR-0001 still owns provenance, identity, release and publication.

## 1. Decision

The user chose design study 11, "Longform, home first", as the template for the public
wiki. It replaces the reader on the hub and on all twelve topic sites at their existing
URLs. The same decision adds four things:

- a readability audit;
- a reviewed presentation registry for field labels, units and formats;
- derived gameplay joins;
- guides generated from data.

The user's requirement is that a casual player, not a programmer, can read every
player-facing page. Reference data that a player cannot use must not bury the facts a
player needs.

## 2. Audience tiers

Every field shown on a page has one audience:

| Tier | Shown | Examples |
| --- | --- | --- |
| Player | In the entry's summary card and in guides | Damage, durability, magazine size, stack size, how to get it, what it makes |
| Technical | In a collapsed "Technical reference" section on the same page | Game IDs, GUIDs, asset paths, evidence locators, raw stored values, captures |
| Hidden | Nowhere on the page; still kept in packs and provenance | Constant placeholders such as a field that is `0` on every item |

ADR-0001 §4 still applies. Identifiers and evidence stay on every entry, one click away,
never removed. A field that the registry does not list is technical by default. A new field
never appears in the player view until someone classifies it.

## 3. Presentation registry

`presentation/fields.json` records, for each entity kind and field: the player label, the
unit, the format, the tier, the group, any sentinel values, and any override that depends on
subtype. One example is a bow's `_baseDamage`, which is a multiplier and not a damage value.

The first version comes from the readability audit (§6), and the user reviews it once. After
that it is maintained data, like `identity/corrections.json`. It is not a run-time approval
step.

Formatting happens at build time. A pack carries the display string next to the raw value.
Float32 noise is rounded for display only, and the exact stored value stays in the technical
tier.

Records that share a display name get distinct player names, derived from their sources. For
example, "M1891 (crafted)" and "M1891 (loot)". Identity rules are unchanged.

## 4. Derived gameplay joins

New adapters add these relationships, each with an evidence level:

- biome ring order;
- biome to mineable resource;
- container to biome, marked as inferred from the bundle name;
- vegetation to collectible;
- an acquisition summary for each item;
- the earliest ring in which each recipe and its workbench chain can be made.

Rates stay labelled as rates. ADR-0001 §4 forbids presenting them as probabilities without a
verified selection rule.

## 5. Guides

Guides live in the hub, which already owns the `guide` kind. Each guide is a data spec: a
list of sections, and for each section a query over the derived graph and a sentence or
table template. The generator renders them in the normal deterministic build, so identical
inputs produce identical bytes.

Each guide names the build it was generated from.

Judgement text, such as advice or recommendations, is optional. It uses the checked claims
of [CURATED.md](../CURATED.md), attached to a guide section. When a claim fails its check,
only that claim is withdrawn. A guide is complete without any claims.

The first guides are:

- Getting started
- Progression by biome
- Choosing a weapon
- Crafting stations

## 6. Readability checks

`tools/audit_readability.py` walks the released packs and the catalog. It reports:

- unlabelled or identifier-shaped labels;
- float noise;
- sentinel and constant fields;
- untranslated or empty text;
- identifiers leaking into the player tier;
- duplicate display names;
- records with no source;
- debug items.

A jargon lint over the player tier and the guides is a test. It fails on identifiers, raw
enum integers and unformatted floats.

## 7. Reader

The shell in `wikibuild/web/` takes study 11's design:

- The home page has search first, a topic map, and scroll charts computed from counts.
- Entry pages open with a player summary card. The technical record follows it, collapsed.
- Guide pages are the long reads.

Pack loading, hash checks, version selection, the release bootstrap and route shapes are
unchanged. The new reader must render the packs of every captured snapshot. The stack
remains standard-library Python and native browser APIs, with self-hosted OFL fonts and no
framework.

## 8. Acceptance

[ACCEPTANCE.md](../ACCEPTANCE.md) rows A30 to A36 hold each requirement's failing case and
its proof. Publication follows ADR-0001 §6. It replaces the live sites only after the user
has read the local preview and chosen to publish.
