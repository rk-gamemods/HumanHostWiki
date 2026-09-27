"""Reviewed presentation and infrastructure fields, with drift detection.

Each exact class still goes through Selection: newly captured fields are logged.
Only its type/count summary is emitted. No private telemetry, visual settings or
per-instance empty records are exported. These decisions concern serialized
fields; they do not claim to explain every method in the class.
"""

from .schema import component


def reviewed(assembly, name, omitted, reason):
    return component(assembly, name, "component", "technical-reference", {}, omitted,
                     notes=reason, summary_only=True)


SPECS = (
    reviewed("Assembly-CSharp", "NM_Wind",
             "FlexNoiseWorldSize GustMaskTexture GustScale GustSpeed GustWorldSize NoiseTexture ShiverNoiseWorldSize Turbulence WindSpeed point1 point2 point3 point4",
             "Vegetation shader wind configuration; visual settings omitted."),
    reviewed("Assembly-CSharp", "Reporter",
             "Initialized UserData _DebugLabelColor debugMode fps fpsText images maxSize numOfCircleToShow show size",
             "Diagnostic log overlay; user data, telemetry and UI fields omitted."),
    reviewed("Assembly-CSharp", "ReporterMessageReceiver", "",
             "Diagnostic overlay callbacks; no captured domain fields."),
    reviewed("Assembly-CSharp", "SentryInitializer", "_reporter",
             "Diagnostic reporter binding; no telemetry or runtime log data exported."),
    reviewed("Bicycle", "SBPScripts.BicycleSounds",
             "bodyHitAudioSource freeWheelAudioSource pedallingAudioSource tyreHitFAudioSource tyreHitRAudioSource",
             "Bicycle audio-source bindings; audio payloads omitted."),
    reviewed("File_Verification", "File_Verification", "corruptionDialog",
             "Installation-integrity dialog binding; no domain configuration."),
    reviewed("Item_Info", "ItemInfo_TerraBlock", "_dropModelMat",
             "Dropped terrain block's visual material binding; material payload omitted."),
    reviewed("My_Pool", "My_Pool_Core", "",
             "Runtime object-pool service; no captured domain fields."),
    reviewed("Refs_KeepAlive", "Refs_KeepAlive", "_AssetRefs",
             "Addressable asset lifetime bindings; no gameplay property values."),
    reviewed("Trap", "Trap_Sound_Set", "",
             "Named trap audio routing marker; no captured fields beyond Unity identity."),
    reviewed("Sound_FX", "Decal_Fader", "_FadeOverTime _Projector _destroyDelay",
             "Decal display and fade settings; visual payloads omitted."),
    reviewed("Sound_FX", "Decal_Handler", "_decal_Projector",
             "Decal projector binding; visual payload omitted."),
    reviewed("Sound_FX", "Gun_Aim_Reload_Sets",
             "_AimSounds _AimVolumes _CockSounds _CockVolumes _DryFireSounds _DryFireVolumes _LoadSounds _LoadVolumes _SlideUnlockSounds _SlideUnlockVolumes _UnLoadSounds _UnLoadVolumes",
             "Gun handling audio clips and playback volumes; payloads omitted."),
    reviewed("Sound_FX", "Gun_Fire_Sets", "_FireSounds _FireVolumes",
             "Gunfire audio clips and playback volumes; payloads omitted."),
    reviewed("Sound_FX", "ParticleDecalCollision",
             "DecalPrefabs decalRecycleCount destroyDelay limitAngle maxAngle maxScale minAngle minScale randomRotation",
             "Particle collision decal placement and recycling; visual payloads omitted."),
    reviewed("Sound_FX", "Particle_Handler", "_hasBFX_BloodSettings _originColors _particleRenders _particles",
             "Particle renderer/color bindings; visual payloads omitted."),
)
