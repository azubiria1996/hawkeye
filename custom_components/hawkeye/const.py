"""Constantes de la integración Hawkeye."""

DOMAIN = "hawkeye"
PLATFORMS = ["sensor"]

# Versión del schema de la entry. Si cambia el shape de los datos guardados,
# incrementar y migrar.
CONFIG_VERSION = 1

# Storage para overrides puntuales (por día)
STORAGE_KEY = f"{DOMAIN}_overrides"
STORAGE_VERSION = 1

# ── Configuración: claves de la entry ─────────────────────────────────
CONF_TOTAL_CONSUMPTION_SENSOR = "total_consumption_sensor"
CONF_PRICE_SENSOR = "price_sensor"
CONF_PRICE_FALLBACK = "price_fallback_eur_kwh"
CONF_ASSETS = "assets"

# Por cada asset:
ASSET_TYPE = "type"
ASSET_NAME = "name"
ASSET_SENSOR = "sensor"

# Para appliance:
ASSET_DAYS = "days_of_week"            # lista de int 0..6
ASSET_NAIVE_START_HOUR = "naive_start_hour"
ASSET_NAIVE_DURATION_HOURS = "naive_duration_hours"

# Para EV:
ASSET_NAIVE_ARRIVAL_HOUR = "naive_arrival_hour"
ASSET_MAX_POWER_KW = "max_power_kw"

# Tipos de asset
ASSET_TYPE_APPLIANCE = "appliance"
ASSET_TYPE_EV = "ev"
ASSET_TYPE_SOLAR = "solar"

# ── Servicios ──────────────────────────────────────────────────────────
SERVICE_RECALCULATE = "recalculate_today"
SERVICE_SET_OVERRIDE = "set_override"
SERVICE_CLEAR_OVERRIDE = "clear_override"

# ── Atributos de los sensores ──────────────────────────────────────────
ATTR_TARGET_DATE = "target_date"
ATTR_HOURLY_KWH = "hourly_kwh"
ATTR_HOURLY_EUR = "hourly_eur"
ATTR_BASELINE_HOURLY_KWH = "baseline_hourly_kwh"
ATTR_REAL_HOURLY_KWH = "real_hourly_kwh"
ATTR_NON_MANAGEABLE_KWH = "non_manageable_hourly_kwh"
ATTR_APPLIANCE_NAIVES = "appliance_naives"
ATTR_APPLIANCE_REALS = "appliance_reals"
ATTR_EV_NAIVE = "ev_naive"
ATTR_EV_REAL = "ev_real"
ATTR_SOLAR_KWH = "solar_kwh"
ATTR_WARNINGS = "warnings"
ATTR_PRICE_SOURCE = "price_source"
ATTR_OVERRIDES_TODAY = "overrides_today"
ATTR_LAST_HOUR_PROCESSED = "last_hour_processed"
