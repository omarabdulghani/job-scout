"""Deterministic market, employment, sponsorship, and career-lane metadata."""

from __future__ import annotations

import re
from typing import Any

from agent.search_scope import MARKET_PROFILES, normalize_search_scope


CAREER_LANES = ("primary", "bridge", "fallback", "other")
SPONSORSHIP_STATUSES = (
    "not_required",
    "confirmed",
    "likely",
    "unknown",
    "unavailable",
)
SUPPORT_STATUSES = ("not_required", "confirmed", "unavailable", "unknown")
CONTRACT_TYPES = (
    "permanent",
    "fixed-term",
    "temporary",
    "contract",
    "internship",
    "unknown",
)

_PRIMARY_MARKERS = (
    "ux",
    "ui designer",
    "product designer",
    "digital designer",
    "creative",
    "brand",
    "content",
    "social media",
    "community",
    "ugc",
    "influencer",
    "campaign",
    "e-commerce",
    "ecommerce",
    "web content",
    "digital merchand",
    "product coordinator",
    "product specialist",
    "product marketing",
    "junior product manager",
)
_BRIDGE_MARKERS = (
    "customer success",
    "customer experience",
    "partner experience",
    "customer operations",
    "product operations",
    "digital operations",
    "project coordinator",
    "project assistant",
    "operations coordinator",
    "business analyst",
    "data analyst",
    "reporting analyst",
    "insights analyst",
    "bi trainee",
    "analytics trainee",
    "implementation consultant",
    "graduate programme",
    "graduate program",
    "traineeship",
    "procurement trainee",
    "supply chain trainee",
    "research assistant",
    "clinical study assistant",
)
_FALLBACK_MARKERS = (
    "customer support",
    "customer service",
    "back office",
    "order processing",
    "retail sales assistant",
    "sales assistant",
    "receptionist",
    "office assistant",
    "administrative assistant",
    "hospitality",
    "travel consultant",
)
_SPONSORSHIP_CONFIRMED = (
    "visa sponsorship provided",
    "visa sponsorship is provided",
    "sponsor your visa",
    "employment visa provided",
    "work visa provided",
    "residency visa provided",
    "visa and relocation support",
)
_SPONSORSHIP_LIKELY = (
    "relocation support",
    "relocation package",
    "international candidates",
    "global mobility",
    "work permit assistance",
    "visa assistance",
    "flight allowance",
    "annual flight",
    "housing allowance",
)
_SPONSORSHIP_UNAVAILABLE = (
    "no visa sponsorship",
    "unable to sponsor",
    "cannot sponsor",
    "must already have a valid visa",
    "must have a valid visa",
    "existing work visa required",
    "local visa required",
    "own visa required",
    "family visa required",
    "valid iqama required",
    "transferable iqama required",
    "nationals only",
)
_ENGLISH_SIGNALS = (
    "english",
    "international team",
    "working language",
    "global team",
    "multicultural",
)
_GERMAN_REQUIRED = (
    "fluent german",
    "german required",
    "german is required",
    "native german",
    "professional german",
    "c1 german",
    "c2 german",
    "verhandlungssicheres deutsch",
    "flieend deutsch",
    "flie\u00dfend deutsch",
    "deutschkenntnisse zwingend",
    "sehr gute deutschkenntnisse",
)
_GERMAN_OPTIONAL = (
    "german is a plus",
    "german preferred",
    "german would be a plus",
    "deutsch von vorteil",
    "deutsch wunschenswert",
    "deutsch w\u00fcnschenswert",
)
_GERMAN_COMMON = (
    " wir ",
    " und ",
    " der ",
    " die ",
    " das ",
    " deine ",
    " unser ",
    " aufgaben ",
    " anforderungen ",
    " bewerbung ",
    " arbeitszeit ",
    " kenntnisse ",
)


def combined_job_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(key) or "")
        for key in (
            "title",
            "company",
            "location",
            "description",
            "preview_text",
            "reason",
            "interview_probability_reason",
            "employment_type",
            "workplace_type",
        )
    ).lower()


def infer_employment_metadata(job: dict[str, Any]) -> dict[str, Any]:
    text = combined_job_text(job)
    employment_types: list[str] = []

    def add(value: str) -> None:
        if value not in employment_types:
            employment_types.append(value)

    if re.search(r"\bfull[- ]?time\b|\bvoltijd\b|\bfulltime\b", text):
        add("full-time")
    if re.search(r"\bpart[- ]?time\b|\bdeeltijd\b|\bparttime\b", text):
        add("part-time")
    if re.search(r"\bintern(ship)?\b|\bstage\b", text):
        add("internship")
    if re.search(r"\bcontract(or)?\b|\bfreelance\b|\bzzp\b", text):
        add("contract")
    if re.search(r"\btemporary\b|\btemp\b|\btijdelijk\b", text):
        add("temporary")

    weekly_hours = ""
    hour_match = re.search(
        r"\b(\d{1,2})\s*(?:-|\u2013|to|tot)\s*(\d{1,2})\s*(?:hours?|hrs?|uur)\b",
        text,
    )
    if hour_match:
        weekly_hours = f"{hour_match.group(1)}-{hour_match.group(2)} hours"
        low, high = int(hour_match.group(1)), int(hour_match.group(2))
        if high >= 32:
            add("full-time")
        if low < 36:
            add("part-time")
    else:
        hour_match = re.search(r"\b(\d{1,2})\s*(?:hours?|hrs?|uur)\b", text)
        if hour_match:
            weekly_hours = f"{hour_match.group(1)} hours"
            hours = int(hour_match.group(1))
            add("full-time" if hours >= 36 else "part-time")

    flexible_hours = bool(
        {"full-time", "part-time"}.issubset(set(employment_types))
        or re.search(
            r"part[- ]?time (?:is )?(?:possible|available|negotiable)|"
            r"full[- ]?time (?:or|and) part[- ]?time|"
            r"hours (?:are )?(?:flexible|negotiable)|"
            r"flexible working hours|"
            r"deeltijd mogelijk",
            text,
        )
    )
    return {
        "employment_types": employment_types,
        "weekly_hours": weekly_hours,
        "flexible_hours": flexible_hours,
    }


def evaluate_employment_policy(
    employment_types: list[str] | tuple[str, ...] | None,
    flexible_hours: bool,
    search_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    scope = normalize_search_scope(search_scope or {})
    preference = str(scope.get("employment") or "full-time-preferred")
    normalized_types = {
        str(value or "").strip().lower()
        for value in employment_types or []
        if str(value or "").strip()
    }
    has_full_time = "full-time" in normalized_types
    has_part_time = "part-time" in normalized_types
    flexible = bool(
        flexible_hours
        or (has_full_time and has_part_time)
    )

    result = {
        "employment_match": "unknown",
        "employment_eligible": True,
        "employment_score_adjustment": 0,
        "employment_adjustment_reason": "",
    }
    if scope.get("legacy_mode") or not normalized_types:
        return result

    if preference == "full-time-only":
        if has_part_time and not has_full_time and not flexible:
            return {
                "employment_match": "incompatible",
                "employment_eligible": False,
                "employment_score_adjustment": 0,
                "employment_adjustment_reason": "Part-time-only role does not match the Full-time only search.",
            }
        if has_full_time or flexible:
            result["employment_match"] = "accepted"
        return result

    if preference == "part-time-only":
        if has_full_time and not has_part_time and not flexible:
            return {
                "employment_match": "incompatible",
                "employment_eligible": False,
                "employment_score_adjustment": 0,
                "employment_adjustment_reason": "Full-time-only role does not match the Part-time only search.",
            }
        if has_part_time or flexible:
            result["employment_match"] = "accepted"
        return result

    if preference == "full-time-preferred":
        if has_full_time and not has_part_time and not flexible:
            return {
                "employment_match": "preferred",
                "employment_eligible": True,
                "employment_score_adjustment": 3,
                "employment_adjustment_reason": "Explicit full-time work matches the selected preference.",
            }
        if has_part_time and not has_full_time and not flexible:
            return {
                "employment_match": "accepted_with_penalty",
                "employment_eligible": True,
                "employment_score_adjustment": -6,
                "employment_adjustment_reason": "Part-time-only work is allowed but below the Full-time preferred setting.",
            }
        if flexible:
            result["employment_match"] = "accepted"
        return result

    if preference in {"full-or-part-time", "any"}:
        if has_full_time or has_part_time or flexible:
            result["employment_match"] = "accepted"
        return result

    return result


def classify_sponsorship(
    job: dict[str, Any],
    search_scope: dict[str, Any] | None,
) -> str:
    scope = normalize_search_scope(search_scope or {})
    if scope.get("sponsorship_policy") == "not_required":
        return "not_required"
    text = combined_job_text(job)
    if any(marker in text for marker in _SPONSORSHIP_UNAVAILABLE):
        return "unavailable"
    if any(marker in text for marker in _SPONSORSHIP_CONFIRMED):
        return "confirmed"
    if any(marker in text for marker in _SPONSORSHIP_LIKELY):
        return "likely"
    return "unknown"


def infer_international_metadata(
    job: dict[str, Any],
    search_scope: dict[str, Any] | None,
    *,
    ai_result: dict[str, Any] | None = None,
    user_country: str = "",
) -> dict[str, Any]:
    scope = normalize_search_scope(search_scope or {})
    ai_result = ai_result or {}
    text = combined_job_text(job)
    
    job_country = infer_country(job, scope).strip().lower()
    user_country_normalized = user_country.strip().lower()
    
    international = bool(
        not user_country_normalized 
        or (job_country and user_country_normalized and job_country != user_country_normalized)
    )

    def support_status(
        confirmed_patterns: tuple[str, ...],
        unavailable_patterns: tuple[str, ...] = (),
        *,
        not_required: bool = False,
        ai_key: str,
    ) -> str:
        if not_required:
            return "not_required"
        if any(pattern in text for pattern in unavailable_patterns):
            return "unavailable"
        if any(pattern in text for pattern in confirmed_patterns):
            return "confirmed"
        ai_value = str(ai_result.get(ai_key) or "").strip().lower()
        return ai_value if ai_value in SUPPORT_STATUSES else "unknown"

    relocation_support = support_status(
        (
            "relocation support",
            "relocation package",
            "relocation assistance",
            "relocation allowance",
            "global mobility",
        ),
        ("no relocation support", "relocation is not provided"),
        not_required=not international,
        ai_key="relocation_support",
    )
    housing_support = support_status(
        (
            "housing allowance",
            "accommodation provided",
            "company accommodation",
            "housing provided",
        ),
        ("no housing allowance", "accommodation is not provided"),
        not_required=not international,
        ai_key="housing_support",
    )
    health_insurance = support_status(
        (
            "health insurance",
            "medical insurance",
            "private medical",
            "healthcare coverage",
        ),
        not_required=not international,
        ai_key="health_insurance",
    )
    annual_flight_support = support_status(
        (
            "annual flight",
            "annual airfare",
            "flight allowance",
            "yearly flight",
            "home flight",
        ),
        not_required=not international,
        ai_key="annual_flight_support",
    )

    compensation_text = ""
    compensation_match = re.search(
        r"(?:eur|aed|sar|qar|kwd|usd|gbp|\$)\s*[\d,.]+"
        r"(?:\s*(?:-|to)\s*(?:eur|aed|sar|qar|kwd|usd|gbp|\$)?\s*[\d,.]+)?"
        r"(?:\s*(?:per|/)\s*(?:hour|month|year|annum))?",
        text,
        flags=re.I,
    )
    if compensation_match:
        compensation_text = re.sub(r"\s+", " ", compensation_match.group(0)).strip()
    elif ai_result.get("compensation_text"):
        compensation_text = re.sub(
            r"\s+",
            " ",
            str(ai_result.get("compensation_text") or "").strip(),
        )[:160]

    contract_type = "unknown"
    contract_patterns = (
        ("permanent", ("permanent contract", "indefinite contract", "onbepaalde tijd")),
        ("fixed-term", ("fixed-term", "fixed term", "bepaalde tijd")),
        ("internship", ("internship", "intern ", "stage ")),
        ("temporary", ("temporary", "tijdelijk", "temp role")),
        ("contract", ("contractor", "freelance", "zzp", "consultancy contract")),
    )
    for candidate, patterns in contract_patterns:
        if any(pattern in text for pattern in patterns):
            contract_type = candidate
            break
    if contract_type == "unknown":
        ai_contract = str(ai_result.get("contract_type") or "").strip().lower()
        if ai_contract in CONTRACT_TYPES:
            contract_type = ai_contract

    return {
        "relocation_support": relocation_support,
        "housing_support": housing_support,
        "health_insurance": health_insurance,
        "annual_flight_support": annual_flight_support,
        "compensation_text": compensation_text,
        "contract_type": contract_type,
    }


def classify_career_lane(job: dict[str, Any]) -> str:
    title = str(job.get("title") or "").lower()
    if any(marker in title for marker in _PRIMARY_MARKERS):
        return "primary"
    if any(marker in title for marker in _BRIDGE_MARKERS):
        return "bridge"
    if any(marker in title for marker in _FALLBACK_MARKERS):
        return "fallback"

    domain = str(job.get("domain") or "").lower()
    if any(marker in domain for marker in ("ux", "design", "brand", "content", "ecommerce")):
        return "primary"
    if any(marker in domain for marker in ("data", "operations", "customer success", "research")):
        return "bridge"

    text = combined_job_text(job)
    if any(marker in text for marker in _PRIMARY_MARKERS):
        return "primary"
    if any(marker in text for marker in _BRIDGE_MARKERS):
        return "bridge"
    if any(marker in text for marker in _FALLBACK_MARKERS):
        return "fallback"
    return "other"


def classify_historical_career_lane(job: dict[str, Any]) -> str:
    """Classify legacy jobs only when independent evidence agrees."""

    def marker_lane(value: Any) -> str:
        text = str(value or "").lower()
        if any(marker in text for marker in _PRIMARY_MARKERS):
            return "primary"
        if any(marker in text for marker in _BRIDGE_MARKERS):
            return "bridge"
        if any(marker in text for marker in _FALLBACK_MARKERS):
            return "fallback"
        return ""

    domain_category = str(job.get("domain_category") or "").upper()
    domain_support: dict[str, set[str]] = {
        "UX_UI_PRODUCT_DESIGN": {"primary"},
        "BRAND_CREATIVE_CONTENT": {"primary"},
        "ECOMMERCE_WEB_DIGITAL_OPS": {"primary", "bridge"},
        "MARKETING_COMMUNICATIONS": {"primary"},
        "DATA_ANALYTICS_BUSINESS": {"bridge"},
        "PRODUCT_PROJECT_OPERATIONS": {"bridge"},
        "PROCUREMENT_SUPPLY_CHAIN": {"bridge"},
        "RESEARCH_ADMIN": {"bridge"},
        "CUSTOMER_SUCCESS_OPS_SUPPORT": {"bridge", "fallback"},
        "FALLBACK_INCOME": {"fallback"},
    }
    supported_lanes = domain_support.get(domain_category, set())
    title_lane = marker_lane(job.get("title"))
    description_lane = marker_lane(
        job.get("description")
        or job.get("description_preview")
        or job.get("reason")
        or job.get("interview_probability_reason")
    )
    discovery_groups = {
        str(value or "").strip().lower()
        for value in [
            job.get("search_group"),
            *(
                job.get("matched_search_groups", [])
                if isinstance(job.get("matched_search_groups"), list)
                else []
            ),
        ]
        if str(value or "").strip().lower() in {"primary", "bridge", "fallback"}
    }

    if title_lane and title_lane in supported_lanes:
        return title_lane
    if title_lane and description_lane == title_lane:
        return title_lane
    for lane in ("primary", "bridge", "fallback"):
        if lane in discovery_groups and lane in supported_lanes:
            return lane
    return "other"


def infer_country(job: dict[str, Any], search_scope: dict[str, Any] | None) -> str:
    scope = normalize_search_scope(search_scope or {})
    location = str(job.get("location") or "").lower()
    for market, profile in MARKET_PROFILES.items():
        if profile["country"].lower() in location:
            return profile["country"]
        if any(
            candidate.lower() in location
            for candidate in profile.get("locations", [])
            if candidate.lower() not in {"remote", profile["country"].lower()}
        ):
            return profile["country"]
    return str(scope.get("country") or "")


def german_language_assessment(job: dict[str, Any]) -> dict[str, Any]:
    text = f" {combined_job_text(job)} "
    required = next((marker for marker in _GERMAN_REQUIRED if marker in text), "")
    optional = next((marker for marker in _GERMAN_OPTIONAL if marker in text), "")
    english_signal = any(marker in text for marker in _ENGLISH_SIGNALS)
    german_hits = sum(text.count(marker) for marker in _GERMAN_COMMON)
    predominantly_german = german_hits >= 5 and not english_signal
    return {
        "german_required": bool(required),
        "german_required_marker": required,
        "german_optional": bool(optional),
        "german_optional_marker": optional,
        "english_signal": english_signal,
        "predominantly_german": predominantly_german,
    }


def market_eligibility(
    job: dict[str, Any],
    search_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    scope = normalize_search_scope(search_scope or {})
    market = scope["search_market"]
    reasons: list[str] = []
    concerns: list[str] = []
    sponsorship = classify_sponsorship(job, scope)

    if market == "germany":
        language = german_language_assessment(job)
        if language["german_required"]:
            reasons.append("Mandatory German requirement")
        elif language["predominantly_german"]:
            reasons.append("German-language posting without an English working-language signal")
        elif language["german_optional"]:
            concerns.append("German preferred")
    elif scope.get("sponsorship_policy") == "required":
        if sponsorship == "unavailable":
            reasons.append("Employer requires an existing local visa or does not sponsor")
        elif sponsorship == "unknown":
            concerns.append("Visa sponsorship is not confirmed")
        elif sponsorship == "likely":
            concerns.append("International hiring signals found; sponsorship should be confirmed")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "concerns": concerns,
        "sponsorship_status": sponsorship,
    }


def enrich_job_scope_metadata(
    job: dict[str, Any],
    search_scope: dict[str, Any] | None,
    *,
    ai_result: dict[str, Any] | None = None,
    user_country: str = "",
) -> dict[str, Any]:
    scope = normalize_search_scope(search_scope or {})
    ai_result = ai_result or {}
    employment = infer_employment_metadata(job)
    lane = str(ai_result.get("career_lane") or "").strip().lower()
    if lane not in CAREER_LANES:
        lane = classify_career_lane(job)
    eligibility = market_eligibility(job, scope)
    ai_sponsorship = str(ai_result.get("sponsorship_status") or "").strip().lower()
    if (
        eligibility["sponsorship_status"] == "unknown"
        and ai_sponsorship in SPONSORSHIP_STATUSES
    ):
        eligibility["sponsorship_status"] = ai_sponsorship
        eligibility["reasons"] = []
        eligibility["concerns"] = []
        if ai_sponsorship == "unavailable":
            eligibility["reasons"].append(
                "Employer requires an existing local visa or does not sponsor"
            )
        elif ai_sponsorship == "unknown":
            eligibility["concerns"].append("Visa sponsorship is not confirmed")
        elif ai_sponsorship == "likely":
            eligibility["concerns"].append(
                "International hiring signals found; sponsorship should be confirmed"
            )
        eligibility["eligible"] = not eligibility["reasons"]
    ai_employment = ai_result.get("employment_types")
    if isinstance(ai_employment, str):
        ai_employment = [ai_employment]
    for value in ai_employment or []:
        normalized = str(value or "").strip().lower()
        if normalized and normalized not in employment["employment_types"]:
            employment["employment_types"].append(normalized)
    employment_policy = evaluate_employment_policy(
        employment["employment_types"],
        bool(employment["flexible_hours"] or ai_result.get("flexible_hours")),
        scope,
    )

    concerns = list(eligibility["concerns"])
    for value in ai_result.get("market_concerns") or []:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in concerns:
            concerns.append(cleaned)

    international_metadata = infer_international_metadata(
        job,
        scope,
        ai_result=ai_result,
        user_country=user_country,
    )

    return {
        "career_lane": lane,
        "search_market": scope["search_market"],
        "country": infer_country(job, scope),
        "employment_types": employment["employment_types"],
        "weekly_hours": employment["weekly_hours"]
        or str(ai_result.get("weekly_hours") or ""),
        "flexible_hours": bool(
            employment["flexible_hours"]
            or ai_result.get("flexible_hours")
            or {"full-time", "part-time"}.issubset(
                set(employment["employment_types"])
            )
        ),
        **employment_policy,
        "sponsorship_status": eligibility["sponsorship_status"],
        "sponsorship_policy": scope.get("sponsorship_policy"),
        "relocation_required": bool(
            scope["search_market"] not in {"netherlands"}
            and not scope.get("legacy_mode")
        ),
        **international_metadata,
        "market_concerns": concerns,
        "market_eligible": eligibility["eligible"],
        "market_rejection_reasons": eligibility["reasons"],
    }


def cap_score_for_scope(
    score: int,
    metadata: dict[str, Any],
) -> tuple[int, str]:
    numeric_score = max(0, min(100, int(score or 0)))
    if (
        metadata.get("sponsorship_status") == "unknown"
        and metadata.get("sponsorship_policy") == "required"
        and numeric_score >= 70
    ):
        return 69, "Visa sponsorship is not confirmed, so this role requires human review."
    return numeric_score, ""
