"""Versioned search-scope profiles shared by CLI, controller, and dashboard."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA_VERSION = "search_scope.v1"
SEARCH_MARKETS = [
    "netherlands",
    "germany",
    "uae",
    "saudi-arabia",
    "qatar",
    "kuwait",
]
EMPLOYMENT_PREFERENCES = (
    "full-time-preferred",
    "full-time-only",
    "part-time-only",
    "full-or-part-time",
    "any",
)
LINKEDIN_RADIUS_KM_TO_MILES = {
    0: 0,
    8: 5,
    16: 10,
    40: 25,
    80: 50,
    160: 100,
}
LINKEDIN_EMPLOYMENT_CODES = {
    "full-time-preferred": ("F", "P"),
    "full-time-only": ("F",),
    "part-time-only": ("P",),
    "full-or-part-time": ("F", "P"),
    "any": (),
}
EMPLOYMENT_LABELS = {
    "full-time-preferred": "Full-time preferred",
    "full-time-only": "Full-time only",
    "part-time-only": "Part-time only",
    "full-or-part-time": "Full-time or part-time equally",
    "any": "Any employment type",
}

MARKET_PROFILES: dict[str, dict[str, Any]] = {
    "netherlands": {
        "label": "Netherlands",
        "availability": "stable",
        "country": "Netherlands",
        "country_codes": ["NL"],
        "default_location": "",
        "locations": [
            "Amstelveen",
            "Amsterdam",
            "Hoofddorp",
            "Haarlem",
            "Schiphol",
            "Utrecht",
            "Hilversum",
            "Weesp",
            "Leiden",
            "Rotterdam",
            "The Hague",
            "Den Haag",
            "Netherlands",
            "Remote",
        ],
        "authorized_without_sponsorship": True,
        "sponsorship_policy": "not_required",
        "language_policy": "dutch_nuanced",
        "compatible_languages": ["English", "Arabic", "Dutch B1"],
    },
    "germany": {
        "label": "Germany",
        "availability": "stable",
        "country": "Germany",
        "country_codes": ["DE"],
        "default_location": "Berlin",
        "locations": [
            "Berlin",
            "Hamburg",
            "Dusseldorf",
            "Cologne",
            "Frankfurt",
            "Munich",
            "Germany",
            "Remote",
        ],
        "authorized_without_sponsorship": True,
        "sponsorship_policy": "not_required",
        "language_policy": "english_required_german_optional",
        "compatible_languages": ["English"],
    },
    "uae": {
        "label": "United Arab Emirates",
        "availability": "stable",
        "country": "United Arab Emirates",
        "country_codes": ["AE"],
        "default_location": "Dubai",
        "locations": ["Dubai", "Abu Dhabi", "United Arab Emirates", "Remote"],
        "authorized_without_sponsorship": False,
        "sponsorship_policy": "required",
        "language_policy": "english_or_arabic",
        "compatible_languages": ["English", "Arabic"],
    },
    "saudi-arabia": {
        "label": "Saudi Arabia",
        "availability": "stable",
        "country": "Saudi Arabia",
        "country_codes": ["SA"],
        "default_location": "Riyadh",
        "locations": ["Riyadh", "Jeddah", "Saudi Arabia", "Remote"],
        "authorized_without_sponsorship": False,
        "sponsorship_policy": "required",
        "language_policy": "english_or_arabic",
        "compatible_languages": ["English", "Arabic"],
    },
    "qatar": {
        "label": "Qatar",
        "availability": "stable",
        "country": "Qatar",
        "country_codes": ["QA"],
        "default_location": "Doha",
        "locations": ["Doha", "Qatar", "Remote"],
        "authorized_without_sponsorship": False,
        "sponsorship_policy": "required",
        "language_policy": "english_or_arabic",
        "compatible_languages": ["English", "Arabic"],
    },
    "kuwait": {
        "label": "Kuwait",
        "availability": "stable",
        "country": "Kuwait",
        "country_codes": ["KW"],
        "default_location": "Kuwait City",
        "locations": ["Kuwait City", "Kuwait", "Remote"],
        "authorized_without_sponsorship": False,
        "sponsorship_policy": "required",
        "language_policy": "english_or_arabic",
        "compatible_languages": ["English", "Arabic"],
    },
}

PLATFORM_CAPABILITIES = {
    "linkedin": {
        "markets": list(SEARCH_MARKETS),
        "radius_km": list(LINKEDIN_RADIUS_KM_TO_MILES),
        "employment_preferences": list(EMPLOYMENT_PREFERENCES),
        "international_scoring": True,
    },
    "indeed": {
        "markets": ["netherlands"],
        "radius_km": [0, 5, 10, 15, 25, 50, 100],
        "employment_preferences": ["any"],
        "international_scoring": False,
        "description_extraction_only": True,
    },
}

BUILT_IN_MISSIONS = {
    "local-career-hunt": {
        "name": "Local Career Hunt",
        "platform": "linkedin",
        "search_market": "netherlands",
        "location": "",
        "radius_km": 40,
        "search_goal": "career-growth",
        "employment": "full-time-preferred",
    },
    "nearby-income-search": {
        "name": "Nearby Income Search",
        "platform": "linkedin",
        "search_market": "netherlands",
        "location": "",
        "radius_km": 16,
        "search_goal": "income",
        "employment": "full-or-part-time",
    },
    "germany-english-career": {
        "name": "Germany English Career",
        "platform": "linkedin",
        "search_market": "germany",
        "location": "Berlin",
        "radius_km": 40,
        "search_goal": "career-growth",
        "employment": "full-time-preferred",
    },
    "gulf-sponsored-career": {
        "name": "Gulf Sponsored Career",
        "platform": "linkedin",
        "search_market": "uae",
        "location": "Dubai",
        "radius_km": 40,
        "search_goal": "career-growth",
        "employment": "full-time-preferred",
    },
}


def platform_capabilities() -> dict[str, Any]:
    return deepcopy(PLATFORM_CAPABILITIES)


def market_profiles() -> dict[str, Any]:
    return deepcopy(MARKET_PROFILES)


def built_in_missions() -> dict[str, Any]:
    return deepcopy(BUILT_IN_MISSIONS)


def normalize_market(value: Any) -> str:
    market = str(value or "netherlands").strip().lower().replace("_", "-")
    if market not in MARKET_PROFILES:
        raise ValueError(f"Unsupported search market: {value}")
    return market


def normalize_employment(value: Any) -> str:
    employment = str(value or "full-time-preferred").strip().lower()
    if employment not in EMPLOYMENT_PREFERENCES:
        raise ValueError(f"Unsupported employment preference: {value}")
    return employment


def normalize_radius(platform: str, value: Any) -> int | None:
    platform_key = str(platform or "linkedin").strip().lower()
    if value in (None, ""):
        return None
    try:
        radius = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid radius: {value}") from exc
    supported = PLATFORM_CAPABILITIES.get(platform_key, {}).get("radius_km", [])
    if radius not in supported:
        raise ValueError(
            f"{platform_key.title()} does not support a {radius} km radius"
        )
    return radius


def location_disables_radius(location: Any, market: str) -> bool:
    normalized = " ".join(str(location or "").split()).lower()
    country = MARKET_PROFILES[normalize_market(market)]["country"].lower()
    return normalized in {"remote", country}


def build_search_scope(
    *,
    platform: str = "linkedin",
    search_market: str = "netherlands",
    location: str | None = None,
    radius_km: int | str | None = 40,
    employment: str = "full-time-preferred",
    search_goal: str = "career-growth",
    search_groups: list[str] | tuple[str, ...] | None = None,
    legacy_mode: bool = False,
    legacy_distance_miles: int | None = None,
    experience_levels: list[str] | tuple[str, ...] | None = None,
    sponsorship_policy: str | None = None,
    workplace_types: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    platform_key = str(platform or "linkedin").strip().lower()
    if platform_key not in PLATFORM_CAPABILITIES:
        raise ValueError(f"Unsupported platform: {platform}")
    market = normalize_market(search_market)
    if market not in PLATFORM_CAPABILITIES[platform_key]["markets"]:
        raise ValueError(
            f"{PLATFORM_CAPABILITIES[platform_key].get('description_extraction_only') and 'Indeed' or platform_key.title()} "
            f"does not support the {MARKET_PROFILES[market]['label']} market in this release"
        )
    profile = MARKET_PROFILES[market]
    cleaned_location = " ".join(
        str(location or profile["default_location"]).split()
    )
    employment_key = normalize_employment(employment)
    if employment_key not in PLATFORM_CAPABILITIES[platform_key]["employment_preferences"]:
        raise ValueError(
            f"{platform_key.title()} does not support {EMPLOYMENT_LABELS[employment_key]}"
        )

    if legacy_mode:
        normalized_radius = None
        radius_miles = int(legacy_distance_miles or 25)
    elif location_disables_radius(cleaned_location, market):
        normalized_radius = None
        radius_miles = None
    else:
        normalized_radius = normalize_radius(platform_key, radius_km)
        radius_miles = (
            LINKEDIN_RADIUS_KM_TO_MILES[normalized_radius]
            if platform_key == "linkedin" and normalized_radius is not None
            else None
        )

    policy = sponsorship_policy if sponsorship_policy is not None else profile["sponsorship_policy"]
    auth_without_sponsorship = (policy == "not_required")
    work_auth = "eu_authorized_no_sponsorship" if auth_without_sponsorship else "visa_required"

    return {
        "schema_version": SCHEMA_VERSION,
        "platform": platform_key,
        "search_market": market,
        "market_label": profile["label"],
        "market_availability": profile.get("availability", "disabled"),
        "country": profile["country"],
        "location": cleaned_location,
        "radius_km": normalized_radius,
        "radius_miles": radius_miles,
        "employment": employment_key,
        "employment_label": EMPLOYMENT_LABELS[employment_key],
        "search_goal": str(search_goal or "career-growth").strip().lower(),
        "search_groups": list(search_groups or []),
        "language_policy": profile["language_policy"],
        "work_authorization_policy": work_auth,
        "sponsorship_policy": policy,
        "authorized_without_sponsorship": auth_without_sponsorship,
        "legacy_mode": bool(legacy_mode),
        "experience_levels": list(experience_levels or ["entry", "associate"]),
        "workplace_types": list(workplace_types or []),
    }


def normalize_search_scope(
    payload: Any,
    *,
    platform: str = "linkedin",
    location: str | None = None,
    legacy_distance_miles: int = 25,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return build_search_scope(
            platform=platform,
            search_market="netherlands",
            location=location or "",
            employment="full-time-preferred",
            search_goal="legacy",
            legacy_mode=True,
            legacy_distance_miles=legacy_distance_miles,
        )
    return build_search_scope(
        platform=payload.get("platform", platform),
        search_market=payload.get("search_market", "netherlands"),
        location=payload.get("location", location),
        radius_km=payload.get("radius_km", 40),
        employment=payload.get("employment", "full-time-preferred"),
        search_goal=payload.get("search_goal", "career-growth"),
        search_groups=payload.get("search_groups", []),
        legacy_mode=bool(payload.get("legacy_mode")),
        legacy_distance_miles=payload.get("radius_miles", legacy_distance_miles),
        experience_levels=payload.get("experience_levels"),
        sponsorship_policy=payload.get("sponsorship_policy"),
        workplace_types=payload.get("workplace_types", []),
    )


def linkedin_employment_codes(scope: dict[str, Any]) -> list[str]:
    if scope.get("legacy_mode"):
        return []
    return list(
        LINKEDIN_EMPLOYMENT_CODES.get(
            normalize_employment(scope.get("employment")),
            (),
        )
    )


def linkedin_workplace_type_codes(scope: dict[str, Any]) -> list[str]:
    types = scope.get("workplace_types") or []
    codes = []
    mapping = {
        "onsite": "1",
        "remote": "2",
        "hybrid": "3"
    }
    for wt in types:
        code = mapping.get(str(wt).lower().strip())
        if code:
            codes.append(code)
    return codes


def search_scope_summary(scope: dict[str, Any]) -> str:
    radius = scope.get("radius_km")
    radius_label = "country-wide" if radius is None else f"{radius} km"
    groups = scope.get("search_groups") or []
    groups_label = " + ".join(str(group).title() for group in groups) or str(
        scope.get("search_goal", "")
    ).replace("-", " ").title()
    language = {
        "english_required_german_optional": "English-friendly jobs",
        "english_or_arabic": "English/Arabic-compatible jobs",
        "dutch_nuanced": "Dutch-aware matching",
    }.get(scope.get("language_policy"), "market-aware language matching")
    return " | ".join(
        [
            str(scope.get("platform", "linkedin")).title(),
            str(scope.get("market_label") or scope.get("country") or ""),
            str(scope.get("location") or ""),
            radius_label,
            groups_label,
            str(scope.get("employment_label") or ""),
            language,
        ]
    )


def scope_learning_key(scope: dict[str, Any], search_group: str) -> str:
    return "|".join(
        [
            str(scope.get("platform", "linkedin")).lower(),
            str(scope.get("search_market", "netherlands")).lower(),
            str(search_group or "unknown").lower(),
            str(scope.get("employment", "full-time-preferred")).lower(),
        ]
    )


def reload_market_profiles() -> None:
    built_in = ["netherlands", "germany", "uae", "saudi-arabia", "qatar", "kuwait"]
    
    # Remove custom keys from MARKET_PROFILES
    for k in list(MARKET_PROFILES.keys()):
        if k not in built_in:
            MARKET_PROFILES.pop(k, None)
            
    # Reset SEARCH_MARKETS
    SEARCH_MARKETS.clear()
    SEARCH_MARKETS.extend(built_in)
    
    # Load custom
    import os
    import json
    path = os.path.join("data", "user_workspace", "custom_markets.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                custom = json.load(f) or {}
            for k, v in custom.items():
                MARKET_PROFILES[k] = v
                if k not in SEARCH_MARKETS:
                    SEARCH_MARKETS.append(k)
        except Exception:
            pass
            
    # Update PLATFORM_CAPABILITIES
    PLATFORM_CAPABILITIES["linkedin"]["markets"] = list(SEARCH_MARKETS)


# Load custom markets on import
reload_market_profiles()
