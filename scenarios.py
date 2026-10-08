"""
Market electricity price profiles and forecast generation scenarios.
Provides realistic wholesale price dynamics including:
- California Duck Curve (High Solar Penetration)
- Summer Heatwave & Scarcity Price Spikes
- Winter Heating Dual-Peak (Morning & Evening)
- Renewable Curtailment / Negative Pricing Events
"""

import numpy as np


def generate_duck_curve(T=48, base_price=35.0):
    """
    Simulates a solar-dominated grid (CAISO 'duck curve'):
    Midday solar depression followed by steep evening ramp and peak.
    """
    prices = np.zeros(T)
    for t in range(T):
        h = t % 24
        solar_dip = -28.0 * np.exp(-0.5 * ((h - 13.0) / 2.0) ** 2)
        morning_bump = 18.0 * np.exp(-0.5 * ((h - 7.5) / 1.5) ** 2)
        evening_peak = 75.0 * np.exp(-0.5 * ((h - 19.5) / 2.0) ** 2)
        night_slack = 5.0 * np.sin(2 * np.pi * h / 24.0)
        prices[t] = max(5.0, base_price + solar_dip + morning_bump + evening_peak + night_slack)
    return prices


def generate_heatwave_spikes(T=48, base_price=42.0):
    """
    Simulates summer heatwave with sharp scarcity price spikes during afternoon cooling hours.
    """
    prices = np.zeros(T)
    for t in range(T):
        h = t % 24
        day_num = t // 24
        temp_effect = 25.0 * np.sin((h - 8.0) * np.pi / 12.0) if 8 <= h <= 22 else -10.0
        spike = 0.0
        if 16 <= h <= 18:
            spike = 160.0 + (day_num * 40.0) + (15.0 if h == 17 else 0.0)
        elif 14 <= h <= 19:
            spike = 60.0
        prices[t] = max(15.0, base_price + temp_effect + spike)
    return prices


def generate_winter_dual_peak(T=48, base_price=38.0):
    """
    Simulates winter electric heating dynamics:
    Pronounced morning peak (7-9 AM) and evening heating peak (6-8 PM).
    """
    prices = np.zeros(T)
    for t in range(T):
        h = t % 24
        morning_peak = 55.0 * np.exp(-0.5 * ((h - 8.0) / 1.5) ** 2)
        evening_peak = 65.0 * np.exp(-0.5 * ((h - 19.0) / 1.8) ** 2)
        midday_plateau = 10.0 * np.exp(-0.5 * ((h - 13.0) / 3.0) ** 2)
        night_dip = -15.0 * np.exp(-0.5 * ((h - 3.5) / 2.0) ** 2)
        prices[t] = max(10.0, base_price + morning_peak + evening_peak + midday_plateau + night_dip)
    return prices


def generate_negative_pricing(T=48, base_price=28.0):
    """
    Simulates extreme renewable curtailment / negative pricing events:
    Midday prices drop below zero due to excess solar/wind. Battery gets paid to charge!
    """
    prices = np.zeros(T)
    for t in range(T):
        h = t % 24
        curtailment = -45.0 * np.exp(-0.5 * ((h - 13.0) / 1.8) ** 2)
        evening_peak = 80.0 * np.exp(-0.5 * ((h - 20.0) / 2.2) ** 2)
        prices[t] = base_price + curtailment + evening_peak
    return prices


SCENARIO_MAP = {
    "California Duck Curve (High Solar)": generate_duck_curve,
    "Summer Heatwave & Scarcity Spikes": generate_heatwave_spikes,
    "Winter Heating (Dual Peak)": generate_winter_dual_peak,
    "Renewable Curtailment (Negative Prices)": generate_negative_pricing,
}

SCENARIO_DESCRIPTIONS = {
    "California Duck Curve (High Solar)": (
        "Midday price depression (down to $7/MWh) caused by massive solar PV feed-in, "
        "followed by a steep evening ramp to $110/MWh as solar drops off and residential load surges. "
        "Ideal for testing classic 4-hour daily cycling."
    ),
    "Summer Heatwave & Scarcity Spikes": (
        "Severe afternoon price spikes ($200-$260/MWh) driven by extreme air-conditioning cooling demand. "
        "Tests battery power-discharge capacity limits during critical peak windows."
    ),
    "Winter Heating (Dual Peak)": (
        "Two daily commercial and heating peaks: morning commute (7-9 AM) and evening lighting/heating (6-8 PM). "
        "Demonstrates whether a battery can execute two complete cycles in a single 24-hour day."
    ),
    "Renewable Curtailment (Negative Prices)": (
        "Deep negative prices (down to -$17/MWh) during solar/wind overgeneration. "
        "The battery earns revenue simply by charging and soaking up grid congestion."
    ),
}


def get_scenario_prices(scenario_name, T=48):
    func = SCENARIO_MAP.get(scenario_name, generate_duck_curve)
    return func(T)


def create_noisy_forecast(true_prices, current_t, horizon, noise_std=0.0, rng=None):
    """
    Generates a forecast for the look-ahead window [current_t, current_t + horizon - 1].
    Uncertainty scales with lead time: immediate hour tau=0 has zero forecast error.
    """
    if rng is None:
        rng = np.random.default_rng(42)

    total_T = len(true_prices)
    window_len = min(horizon, total_T - current_t)
    base_window = true_prices[current_t : current_t + window_len].copy()

    if noise_std <= 1e-4:
        return base_window

    forecast = np.zeros(window_len)
    for tau in range(window_len):
        lead_factor = np.sqrt(tau / max(1.0, float(horizon)))
        err = rng.normal(0.0, noise_std * lead_factor)
        forecast[tau] = base_window[tau] + err

    return forecast
