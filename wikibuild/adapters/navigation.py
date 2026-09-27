"""Map exploration and marker configuration; live discovery and UI assets stay local."""

from .schema import NUMBER as N, V3, component, numbers
from .technical import reviewed

SPECS = (
    component("CompassPro", "CompassNavigatorPro.CompassPro", "world-rule", "world-systems", {
        **numbers("_northDegrees _visibleDistance _visibleMinDistance _nearDistance _visitedDistance _sameAltitudeThreshold _fogOfWarAutoClearRadius _fogOfWarDefaultAlpha _miniMapZoomMin _miniMapZoomMax"),
        **dict.fromkeys("_use3Ddistance _fogOfWarEnabled _fogOfWarAutoClear".split(), int),
        "_fogOfWarCenter": V3, "_fogOfWarSize": V3,
    }, """_alpha _alwaysVisibleInEditMode _autoHide _beaconDefaultAudioClip _bendAmount
_cameraMain _cardinalPointsVerticalOffset _cardinalScale _dontDestroyOnLoad _edgeFadeOut
_edgeFadeOutStart _edgeFadeOutText _edgeFadeOutWidth _endCapsWidth _fadeDuration
_fogOfWarColor _fogOfWarTextureSize _gizmoScale _halfWindsHeight _halfWindsTintColor
_halfWindsWidth _heartbeatDefaultAudioClip _height _horizontalPosition _labelHotZone
_lastAllowBlackFrame _letterSpacing _maxIconSize _minIconSize _miniMapAlpha
_miniMapBackgroundColor _miniMapBorderTexture _miniMapBorderTextureFullScreenMode
_miniMapBrightness _miniMapButtonsScale _miniMapCameraHeightVSFollow _miniMapCameraMaxAltitude
_miniMapCameraMinAltitude _miniMapCameraMode _miniMapCameraSnapshotFrequency _miniMapCameraTilt
_miniMapCaptureSize _miniMapClampBorder _miniMapClampBorderCircular _miniMapContents
_miniMapContentsTexture _miniMapContrast _miniMapEnableShadows _miniMapFollow
_miniMapFullScreenPlaceholder _miniMapFullScreenResolution _miniMapFullScreenSize
_miniMapFullScreenZoomLevel _miniMapIconEvents _miniMapIconPositionShift _miniMapIconSize
_miniMapKeepAspectRatio _miniMapKeepStraight _miniMapLayerMask _miniMapLocation
_miniMapLocationOffset _miniMapLutIntensity _miniMapLutTexture _miniMapMaskSprite
_miniMapMaskSpriteFullScreenMode _miniMapPlayerIconColor _miniMapPlayerIconSize
_miniMapPlayerIconSprite _miniMapPositionAndSize _miniMapResolution _miniMapShowButtons
_miniMapSize _miniMapSnapshotDistance _miniMapSnapshotInterval _miniMapStyle
_miniMapStyleFullScreenContents _miniMapStyleFullScreenContentsTexture _miniMapStyleFullScreenMode
_miniMapVignette _miniMapWorldCenter _miniMapWorldSize _miniMapZoomLevel _ordinalScale
_scaleInDuration _showCardinalPoints _showDistance _showDistanceFormat _showHalfWinds
_showMiniMap _showOrdinalPoints _style _textDuration _textFadeOutDuration _textFont
_textRevealDuration _textRevealEnabled _textRevealLetterDelay _textScale _textShadowEnabled
_textVerticalPosition _titleFont _titleScale _titleShadowEnabled _titleVerticalPosition
_updateInterval _updateIntervalFrameCount _updateIntervalTime _verticalPosition
_visitedDefaultAudioClip _width _worldMappingMode isDirty miniMapFullScreenFreezeCamera
miniMapFullScreenWorldCenter miniMapFullScreenWorldCenterFollows miniMapFullScreenWorldSize""",
       notes="Compass visibility/visit distances and map exploration defaults. Fog bounds are template coordinates; explored pixels and player locations are not captured. World_Map_Mgr also drives reveal behavior, and runtime setters can override these defaults."),
    component("CompassPro", "CompassNavigatorPro.CompassProPOI", "world-rule", "world-systems", {
        **numbers("visibleDistanceOverride visibleMinDistanceOverride visitedDistanceOverride radius"),
        **dict.fromkeys("visibility titleVisibility canBeVisited hideWhenVisited miniMapVisibility".split(), int),
    }, """beaconAudioClip clampPosition computedIconScale distanceToCameraSQR dontDestroyOnLoad
heartbeatAudioClip heartbeatDistance heartbeatEnabled heartbeatInterval iconAlpha iconNonVisited
iconScale iconVisited id isVisited minDistanceText miniMapClampPosition miniMapCurrentIconScale
miniMapIconScale miniMapRotationAngleOffset miniMapShowRotation priority showPlayModeGizmo
tintColor title visitedAudioClip visitedText""",
       notes="Marker visibility and discovery configuration. Positive distance overrides replace compass defaults; zero inherits them. Visibility values are 0 in range, 1 always visible, 2 always hidden. Saved visit state, generated IDs, mutable titles and display/audio assets are omitted."),
    component("CompassPro", "CompassNavigatorPro.CompassProFogVolume", "world-rule", "world-systems", {
        "alpha": N, "border": N, "order": int,
    }, notes="Map fog-volume opacity, border hardness and draw order. Alpha 1 is opaque; volumes apply in ascending order. These are map exploration masks, not atmospheric weather."),
    reviewed("CompassPro", "CompassNavigatorPro.BeaconAnimator", "duration intensity tintColor",
             "Marker beacon pulse animation; no discovery or visibility-distance rules."),
    reviewed("CompassPro", "CompassNavigatorPro.CompassBarMeshModifier", "",
             "Compass-bar mesh deformation; no captured gameplay fields."),
    reviewed("CompassPro", "CompassNavigatorPro.CompassButtonHandler", "",
             "Minimap zoom/fullscreen button event routing; limits belong to CompassPro."),
    reviewed("CompassPro", "CompassNavigatorPro.MiniMapInteraction", "",
             "Minimap pointer-event forwarding; no captured configuration."),
)
