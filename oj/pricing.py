"""Versioned AI price defaults used only for transparent cost estimates.

The catalog deliberately uses peak-hour, cache-miss input rates because the
provider usage payload does not always expose cache-hit token counts.  A user
configured rate always wins for that side of the calculation.
"""

from __future__ import annotations

from urllib.parse import urlsplit

PRICE_UNIT = 1_000_000
OFFICIAL_PRICING_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
OFFICIAL_RATE_VERSION = "deepseek-pricing-checked-2026-09-09"
FALLBACK_RATE_VERSION = "conservative-fallback-2026-09-09"
CACHE_ASSUMPTION = "peak_cache_miss"

# Official DeepSeek prices checked 2026-09-09.  Values are per 1M tokens and
# select the peak cache-miss input price plus the peak output price.
_DEEPSEEK_PEAK_RATES = {
    "USD": {
        "deepseek-v4-flash": (0.44, 1.32),
        "deepseek-v4-flash-vision-exp": (0.44, 1.32),
        "deepseek-v4-pro": (1.32, 3.96),
    }
}

# Unknown providers/models still need a finite estimate.  The USD fallback uses
# the highest price visible in the checked catalog; CNY values are application-
# owned round estimates, not provider-published prices.  Every fallback is
# labeled as such and carries no official pricing URL.  For another currency,
# the USD numeric fallback is retained in that display currency and remains
# explicitly unverified.
_CONSERVATIVE_FALLBACK = {"USD": (1.32, 3.96), "CNY": (9.0, 27.0)}


def _host(provider_url: object) -> str:
    if not isinstance(provider_url, str):
        return ""
    try:
        return (urlsplit(provider_url).hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def resolve_pricing(config: dict) -> dict:
    """Return effective finite rates plus their provenance without mutation."""
    currency = str(config.get("currency") or "USD").upper()
    model = str(config.get("model") or "")
    official = _host(config.get("provider_url")) == "api.deepseek.com"
    catalog = _DEEPSEEK_PEAK_RATES.get(currency, {})
    catalog_rates = catalog.get(model) if official else None
    if catalog_rates is not None:
        default_input, default_output = catalog_rates
        base_source = "deepseek_official_catalog"
        version = OFFICIAL_RATE_VERSION
    else:
        default_input, default_output = _CONSERVATIVE_FALLBACK.get(
            currency, _CONSERVATIVE_FALLBACK["USD"]
        )
        base_source = "conservative_fallback"
        version = FALLBACK_RATE_VERSION

    unit = config.get("price_unit", PRICE_UNIT)
    if type(unit) is not int or unit <= 0:
        unit = PRICE_UNIT
    scale = unit / PRICE_UNIT
    configured_input = config.get("input_price") is not None
    configured_output = config.get("output_price") is not None
    input_price = config.get("input_price") if configured_input else default_input * scale
    output_price = config.get("output_price") if configured_output else default_output * scale
    if configured_input and configured_output:
        source = "configured"
        version = "user-configured"
        assumption = "configured_rates"
    elif configured_input or configured_output:
        source = f"configured+{base_source}"
        assumption = CACHE_ASSUMPTION
    else:
        source = base_source
        assumption = CACHE_ASSUMPTION

    return {
        "input_price": input_price,
        "output_price": output_price,
        "price_unit": unit,
        "currency": currency,
        "rate_source": source,
        "rate_version": version,
        "cache_assumption": assumption,
        "pricing_url": OFFICIAL_PRICING_URL if base_source == "deepseek_official_catalog" else None,
    }
