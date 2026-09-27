"""Trap damage/timing configuration and placement spacing.

Reviewed against Trap_Base.MyOnTriggerEnter, the four concrete
On_Trigger_Enter implementations and Trap_Mgr._Start in build 25548639.
Runtime activation, meshes, colliders, effects and sound routing are omitted.
"""

from .schema import NUMBER, component, numbers

BASE = numbers("_isDynamicTrap _AllowHitAlly _TriggerInterval _TrapDamage _HitReact _TrapSelfDmg _AllowSelfSmash")
EFFECTS = "_BI_Obj _TrapSoundSet _PlayBloodPartile _TriggerCol"
NOTES = ("Serialized trap configuration. Intervals and duration fields are seconds. "
         "Damage and self-damage are configured inputs, not calculated outcomes. "
         "Ally and self-break settings are stored flags; runtime activation is not evaluated here.")

SPECS = (
    component("Trap", "Trap_Spike", "combat-rule", "combat", BASE, EFFECTS, notes=NOTES),
    component("Trap", "Trap_Laser", "combat-rule", "combat", {
        **BASE, **numbers("_LaserContinueSeconds _PerZombieHitInterval"),
    }, EFFECTS + " _BaIMR _BaICopyMR _LaserBeam _LaserSpark _SparkHitBlock _LaserBeamBoxCol _EmiMatIndex _TrapSelfSoundType", notes=NOTES),
    component("Trap", "Trap_RotBlade", "combat-rule", "combat", {
        **BASE, **numbers("_RotSeconds _RotSpeedFactor _RotAxis"),
    }, EFFECTS + " _rotMR _BaIMR _TrapSelfSoundType", notes=NOTES),
    component("Trap", "Trap_SensorSpike", "combat-rule", "combat", {
        **BASE, **numbers("_spikeBackSeconds _spikeStartLoPosY _spikeEndLoPosY"),
    }, EFFECTS + " _spikeMR _BaIMR _TrapSelfSoundType", notes=NOTES),
    component("Trap", "Trap_Mgr", "construction-rule", "construction", {
        "_TrapBInames": [str], "_TrapAlignInters": [NUMBER],
    }, "_TrapSelfSoundSets _trapSounds OnTrapTrigger OnCheckTrapHP OnTrapDisabled",
       notes="Trap placement names and spacing values correspond by array index; distances are Unity world units."),
)
