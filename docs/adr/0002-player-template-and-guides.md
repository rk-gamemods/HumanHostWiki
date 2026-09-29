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

The technical tier shows each stored field name exactly as the game stores it, with rounded
numbers. It does not invent readable-looking labels. "Front View Dis" is neither readable
for a player nor searchable for a modder, while `_FrontViewDis` can be found in the game
code. Construction, AI, survival and world rules and the technical reference are presented
as a game-files reference for modders. The user noted on 2026-09-28 that most of their
fields need the code to make sense. A fact from them reaches the player tier only when a
card or guide needs it, and only after its meaning is confirmed in the game code, as §3
describes.

## 3. Presentation registry

`presentation/fields.json` records, for each entity kind and field: the player label, the
unit, the format, the tier, the group, any sentinel values, and any override that depends on
subtype. One example is a bow's `_baseDamage`, which is a multiplier and not a damage value.

Player labels come from the game's own text wherever the game defines one. The item tooltip
object holds localized titles such as "Damage", "Capacity", "Execute", "Knockdown", "Jam
rate" and "Head Damage". The tooltip code in `UI.decompiled.cs` shows how each value is
formatted: execute and knockdown are percentages rounded to two places, and headshot is
"× 4". The registry names the tooltip key for a field, and the build reads its English text
from the capture, so a wording change in a game update flows through without an edit.
The registry's own label is used only where the game has none.

A field's meaning is confirmed from the code that reads it before the field is classified.
It is not demoted as "unverified" without that check. On 2026-09-28 the user questioned
the first draft on this point. `_baseBladeHitProb` turned out to be the game's "Execute"
chance: on a melee hit with a sharp weapon, the game rolls it and adds 100 damage.

The first version comes from the readability audit (§6), and the user reviews it once. After
that it is maintained data, like `identity/corrections.json`. It is not a run-time approval
step.

Formatting happens at build time. A pack carries the display string next to the raw value.
Float32 noise is rounded for display only, and the exact stored value stays in the technical
tier.

Records that share a display name get distinct player names, derived from their sources. For
example, "M1891 (crafted)" and "M1891 (loot)". Identity rules are unchanged.

Records whose only name is internal, such as combat records named `Axe_Combo_2` or
`Z_Attack_01`, get a wiki name. Where exactly one item or creature uses a record, the name
comes from that user, as in "Crude Axe combat". Otherwise the internal name is split into
words. Pages mark these as wiki names. Any player name that the jargon lint (§6) flags as an
identifier falls back to the same rule, so no internal name reaches a player page.

A building piece or construction rule takes the name of the item that places it, matched through the item's tooltip record. "7_5_Triangle_Small_1.4_Obsidian" reads "Obsidian (Triangle small 1/4)". Other scenery names drop model and detail-level tokens (`SM`, `Prefab`, a trailing `LodN`, Unity's `$N` duplicate suffix) and keep variant numbers.

Search lists player entries before game-file records (the technical reference, assets and configurations). An exact match on a game file never outranks an item.

Values that the game names from a code table use the game's names. Handmade ammo materials
are Copper, Steel, Titanium, Chrome and Tungsten, by position in `_HandCraftBullet`
(`Hand_Tools.decompiled.cs:11213`, `UI.decompiled.cs:3188`).

## 4. Derived gameplay joins

New adapters add these relationships, each with an evidence level:

- biome ring order;
- biome to mineable resource;
- container to biome, marked as inferred from the bundle name;
- vegetation to collectible;
- an acquisition summary for each item;
- the earliest ring in which each recipe and its workbench chain can be made.

The patches of Base terrain near spawn are not a ring. The terrain loader uses
`_BaseBigTerrains` when the chosen layer index is -1, through the border blend next to layer 0
(`Terrain.decompiled.cs` ~7334-7411). That ground can drop every ore, but each rare ore drops
on only 1% of dig hits there, against 20% in its home biome. Counting it as ring 0 would put
every ore at ring 0 and flatten the progression guide. The graph records it separately as
`near_spawn`, and guides mention it once.

Each item, recipe and bench therefore carries two rings:

- `earliest_ring`: the first ring where it can be had at all;
- `main_ring`: the ring where it is reliably had. For a mined material, this is the ring whose
  biome gives the highest chance per dig hit. For a crafted thing, it is the latest main ring
  among its ingredients and its bench.

Guides show `main_ring` and label it "Ring". Each guide's sources line says what the ring
means.

Rates stay labelled as rates. ADR-0001 §4 forbids presenting them as probabilities without a
verified selection rule. A rate that the game itself shows as a percentage, and whose roll is
visible in the code, counts as verified for that display. Execute and knockdown are the
first two.

## 5. Guides

Guides live in the hub, which already owns the `guide` kind. Each guide is a data spec: a
list of sections, and for each section a query over the derived graph and a sentence or
table template. The generator renders them in the normal deterministic build, so identical
inputs produce identical bytes.

Each guide names the build it was generated from.

Judgement text, such as advice or recommendations, is optional. It uses the checked claims
of [CURATED.md](../CURATED.md), attached to a guide section. When a claim fails its check,
only that claim is withdrawn. A guide is complete without any claims.

Guide specs live in `guides/*.json`. A spec names queries over the gameplay graph and gives
sentence and table templates, so its text regenerates on each update.

Guides give distances in metres and kilometres. The game's own tooltip shows projectile
speed in m/s (`UI.decompiled.cs:10105`), so it treats one world unit as one metre. Raw
game units mean nothing to a player.

Guide wording follows fixed rules, so every update reads the same way:

- A phrase inside a ring's section describes that ring only. The starting-ring list never sends a player to the Desert.
- Loot is named by container family ("crates", "cars", "dead bodies", "the abandoned airport"), never by an individual container. It reads "almost everywhere" when an item is looted in 8 or more ring biomes.
- Scenery that a player gathers from is named by kind ("trees", "fallen branches", "rocks", "rubble", "wrecked cars"), from ordered rules in the registry's `guides.harvest_families`. A node of the gathered material itself, such as copper ore rock, is "surface deposits". Anything no rule matches counts as "other scenery", and the guide build reports it after each update. Model names never appear. The first draft named model families ("am165 v ray", "concrete debris big"). The final visual review on 2026-09-29 found that a player cannot use those.
- Benches appear only in bench lists, never again among the recipes they make possible.
- Lists use one "and" and a correct singular ("1 more").
- Biomes have two records each. The terrain record, which carries the gameplay, gets the plain name. The scene record is "(scene)".

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
