"""Serialized weather configuration and clock settings, without visual payloads."""

from .schema import NUMBER as N, Ref, component, fields, numbers

SPECS = (
    component("Weather", "Weather_Settings", "weather", "world-systems", {
        "weatherName": str, "weatherType": int,
        **numbers("maxContinueSeconds minContinueSeconds maxWetnessLevel thunderFrequency rainSecondsToHide rainSecondsToShow"),
    }, """ParticlePrefab ParticleSound ParticleSoundVolume _AGI_Intens_Factor _GI_Intens_Factor
_sunFlareIntens ambientIntensMod fogDensity playParticleDelay reflectionWeightIndoor reflectionWeightOutdoor
skyIntensity sunMoonColorRate volumCloudCover volumCloudDensity"""),
    component("Weather", "WeatherZone_Settings", "world-rule", "world-systems", {
        "_WeatherInfoSets": [fields({"weatherChance": N, "weatherSet": Ref("weather")},
            "cloudLayerColor fogGroundColor fogWholeColor sunColorModAGI volumCloudColor weatherColorFilterAGI weatherColorFilterHGI")],
    }, """BGM_Day BGM_Day_Volume BGM_Emo BGM_Emo_Volume BGM_Night BGM_Night_Volume
_AGI_FarBrightness _AGI_FarColorDirectLRate _AGI_Intense _AGI_IsDenseForest _AGI_IsJungleForest
_AGI_NormalIntens _AGI_Snowland_Use _AGI_SunColorLRate _EmoBGM_Interval _Forest_GI_Factor
_Forest_ILC_BaseFactor _GI_HBAO_Dis _HAO_Radius _HAO_Thick _HGI_Color_factor _HasTraxEffect
_Indoor_Reflect_Factor _Inforest_ILC_factor _Outdoor_GI_Factor _Outdoor_ILC_factor
_Outdoor_Reflect_Factor _SunIntenseCurve _TreeMaxAsFull _exposureAGI _exposureCompenAGI
_exposureCompenHGI _exposureHGI _zoneReflectProbeTex"""),
    component("Enviro3.Runtime", "Enviro.EnviroTimeModule", "time-rule", "world-systems", {
        "Settings": fields(numbers("cycleLengthInMinutes dayLengthModifier nightLengthModifier simulate latitude longitude utcOffset"),
                           "daySerial hourSerial minSerial monthSerial secSerial timeOfDay yearSerial"),
    }, "LST active preset showLocationControls showModuleInspector showSaveLoad showTimeControls"),
)
