"""Explicit infrastructure accounting rules; never infer gameplay from a name.

These assemblies implement engine UI, rendering, animation, audio/visual effects,
serialization or development tooling. Retain technical type/count summaries, not
their payload fields. Game-owned components need domain contracts individually.
New assemblies fall through to an actionable unsupported-component exception.
"""

TECHNICAL_ASSEMBLIES = frozenset("""
AdaptiveGI AdvancedCullingSystem.Runtime Assembly-CSharp-Editor AstarPathfindingProject
BloodFunc Boxophobic.TheVisualEngine.Runtime Circular_Bar Digger.Core Digger.Runtime Drawing
EZ_Outline EasySave Fast_Light FinalIK GPUInstancer GPUInstancer.CrowdAnimations GPUInstancer.Editor
HBAO.HighDefinition.Runtime HTraceAO HTraceWSGI JBooth.MicroSplat.Core Kybernetik.Animancer
MeshFusionPro.Runtime PG.GoreSimulator RaindropFX.HDRP Rich_FX ScreenDamage Sentry.Unity.dll
Shader_Warm Sun_Flares THOR UIResource UltimateTools Unity.Animation.Rigging
Unity.RenderPipelines.Core.Runtime Unity.RenderPipelines.HighDefinition.Runtime Unity.TextMeshPro
Unity.VisualEffectGraph.Runtime UnityEngine UnityEngine.UI VisualDesignCafe.Rendering.Nature.dll
Vuplex.WebView com.thenakeddev.dlss.Runtime.HDRP com.thenakeddev.fsr.Runtime
""".split())

TECHNICAL_CLASSES = frozenset({
    ("Weather", "WeatherOcclusion"), ("Weather", "WeatherOcclusionManager"), ("Weather", "WeatherVisibility"),
    ("Language", "Text_Language_Helper"), ("Language", "Language_Mgr"),
})


def category(row, has_contract, view_classes, payload_types):
    if has_contract:
        return "selected-contract"
    cls, assembly = row.get("class"), row.get("assembly")
    if (assembly, cls) in view_classes:
        return "selected-view"
    if cls:
        if assembly in TECHNICAL_ASSEMBLIES or (assembly, cls) in TECHNICAL_CLASSES:
            return "technical-component"
        return "uninterpreted-component"
    return "payload-omitted" if row["type"] in payload_types else "technical-metadata"
