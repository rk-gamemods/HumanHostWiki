"""Selected Enviro module settings, distinct from the game's weather simulation."""

from .schema import NUMBER as N, Ref, component, fields, numbers
from .technical import reviewed

MODULE_UI = "active preset showModuleInspector showSaveLoad"
SPECS = (
    component("Enviro3.Runtime", "Enviro.EnviroConfiguration", "world-rule", "world-systems", {
        "timeModule": Ref("clock-module"), "Weather": Ref("weather-module"),
    }, "Audio Aurora Effects Environment Lightning Quality Sky flatCloudModule fogModule lightingModule reflectionsModule volumetricCloudModule",
       notes="Time and weather module bindings in the Enviro configuration asset. Rendering/audio module payloads are omitted."),
    component("Enviro3.Runtime", "Enviro.EnviroManager", "world-rule", "world-systems", {
        "dayNightSwitch": N, "Time": Ref("clock-module"), "Weather": Ref("weather-module"),
        "configuration": Ref("environment-configuration"),
    }, """Audio Aurora Camera CameraTag Cameras Effects Environment Events FlatClouds Fog
Lighting Lightning Objects Quality Reflections Sky VolumetricClouds _mySunColor _mySunIntense
dontDestroyOnLoad isNight lastConfiguration lunarTime moonRotationX moonRotationY notFirstFrame
removalZones showEvents showModules showNonTimeControls showSetup showThirdParty solarTime
sunRotationX sunRotationY updateSkyAndLighting updateSkyAndLightingHDRP volumeHDRP""",
       notes="Enviro module bindings and solar-time threshold for its day/night events. Creature_Mgr defines the game's daytime separately; this threshold does not establish zombie or solar-generator schedules. Live clock, sky state and scene bindings are omitted."),
    component("Enviro3.Runtime", "Enviro.EnviroWeatherModule", "world-rule", "world-systems", {
        "Settings": fields({"environmentTransitionSpeed": N, "weatherTypes": [Ref("environment-weather")]},
                           "audioTransitionSpeed auroraTransitionSpeed cloudsTransitionSpeed effectsTransitionSpeed fogTransitionSpeed lightingTransitionSpeed"),
    }, MODULE_UI + " _blendRate currentZone targetWeatherType",
       notes="Enviro weather preset membership and environment interpolation factor. UpdateModule multiplies this factor by frame delta time; it is not a transition duration. Weather_Controller selects presets by name; its gameplay weather values have separate records."),
    component("Enviro3.Runtime", "Enviro.EnviroWeatherType", "world-rule", "world-systems", {
        "environmentOverride": numbers("snowTarget temperatureWeatherMod wetnessTarget windDirectionX windDirectionY windSpeed windTurbulence"),
        "lightningOverride": {"lightningStorm": int, "randomLightningDelay": N},
        "audioOverride": fields({}, "ambientOverride weatherOverride"),
        "auroraOverride": fields({}, "auroraIntensity"),
        "effectsOverride": fields({}, "effectsOverride"),
        "cloudsOverride": fields({}, """ambientLightIntensity anvilBiasLayer1 anvilBiasLayer2
baseErosionIntensityLayer1 baseErosionIntensityLayer2 coverageLayer1 coverageLayer2 curlIntensityLayer1
curlIntensityLayer2 densityLayer1 densityLayer2 densitySmoothnessLayer1 densitySmoothnessLayer2
detailErosionIntensityLayer1 detailErosionIntensityLayer2 dilateCoverageLayer1 dilateCoverageLayer2
dilateTypeLayer1 dilateTypeLayer2 ligthAbsorbtionLayer1 ligthAbsorbtionLayer2 multiScatteringALayer1
multiScatteringALayer2 multiScatteringBLayer1 multiScatteringBLayer2 multiScatteringCLayer1
multiScatteringCLayer2 powderIntensityLayer1 powderIntensityLayer2 scatteringIntensityLayer1
scatteringIntensityLayer2 showLayer1 showLayer2 silverLiningSpreadLayer1 silverLiningSpreadLayer2
typeModifierLayer1 typeModifierLayer2"""),
        "flatCloudsOverride": fields({}, "cirrusCloudsAlpha cirrusCloudsColorPower cirrusCloudsCoverage flatCloudsAbsorbtion flatCloudsAmbientIntensity flatCloudsCoverage flatCloudsDensity flatCloudsLightIntensity"),
        "fogOverride": fields({}, "ambientDimmer anistropy baseHeight directLightMultiplier directLightShadowdimmer extinction fogAttenuationDistance fogColorBlend fogColorMod fogDensity fogDensity2 fogHeight fogHeight2 fogHeightFalloff fogHeightFalloff2 maxHeight scattering"),
        "lightingOverride": fields({}, "ambientIntensityModifier directLightIntensityModifier"),
    }, "showAmbientAudioControls showAudioControls showAuroraControls showCloudControls showEditor showEffectControls showEnvironmentControls showFlatCloudControls showFogControls showLightingControls showLightningControls showWeatherAudioControls",
       notes="Enviro preset environment and lightning targets. They affect a module only when that module is enabled. These values do not replace Weather_Settings or prove character wetness, temperature damage, lightning damage or weather probability. Sky, fog, color, cloud, audio and effect payloads are omitted."),
    reviewed("Enviro3.Runtime", "Enviro.EnviroQuality", "showAurora showEditor showEffects showFlatClouds showFog showVolumeClouds",
             "Rendering quality overrides only; no weather selection or gameplay simulation settings.", {
        "auroraOverride": fields({}, "aurora steps"),
        "flatCloudsOverride": fields({}, "cirrusClouds flatClouds"),
        "fogOverride": fields({}, "fog quality steps volumetrics"),
        "volumetricCloudsOverride": fields({}, "blueNoiseIntensity downsampling dualLayer lodDistance reprojectionBlendTime stepsLayer1 stepsLayer2 volumetricClouds"),
    }),
    reviewed("Enviro3.Runtime", "Enviro.EnviroQualityModule", MODULE_UI + " showQualityControls",
             "Rendering quality preset bindings; no gameplay values.", {
        "Settings": fields({}, "Qualities defaultQuality"),
    }),
    reviewed("Enviro3.Runtime", "Enviro.EnviroSkyModule", MODULE_UI + " _sunMoonColorRate mySkyboxMat showSkyControls showSkyMoonControls showSkyStarsControls showSkySunControls",
             "Sky rendering textures, gradients and intensity curves; no clock or weather-selection parameters.", {
        "Settings": fields({}, """backColorGradient0 backColorGradient1 backColorGradient2
backColorGradient3 backColorGradient4 backColorGradient5 distribution0 distribution1 distribution2
distribution3 frontColorGradient0 frontColorGradient1 frontColorGradient2 frontColorGradient3
frontColorGradient4 frontColorGradient5 galaxyIntensityCurve galaxyTex intensity intensityCurve
mieScatteringIntensityCurve moonColorGradient moonGlowColorGradient moonGlowIntensityCurve
moonGlowTex moonMode moonPhase moonScale moonTex skyAmbientModeHDRP skyExposureHDRP starIntensityCurve
starsTex starsTwinklingSpeed starsTwinklingTex sunDiscColorGradient sunScale sunTex"""),
    }),
    reviewed("Enviro3.Runtime", "Enviro.EnviroLightingModule", MODULE_UI + " additionalLightHDRP directionalLightHDRP exposureHDRP indirectLightingHDRP showAmbientLightingControls showDirectLightingControls showReflectionControls",
             "Lighting/exposure gradients and rendering curves; no weather or daytime simulation rules.", {
        "Settings": fields({}, """ambientColorTintHDRP ambientEquatorColorGradient ambientGroundColorGradient
ambientIntensityCurve ambientIntensityModifier ambientMode ambientSkyColorGradient ambientSkyboxUpdateIntervall
controlExposure controlIndirectLighting diffuseIndirectIntensity directLightIntensityModifier
lightColorTemperatureHDRP lightColorTintHDRP lightingMode moonColorGradient moonIntensityCurve
moonIntensityCurveHDRP reflectionIndirectIntensity sceneExposure setAmbientLighting setDirectLighting
sunColorGradient sunIntensityCurve sunIntensityCurveHDRP updateIntervallFrames"""),
    }),
)
