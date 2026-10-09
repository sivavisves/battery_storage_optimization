"""
Market electricity price profiles and forecast generation scenarios.
Provides realistic wholesale price dynamics with multi-day meteorological evolution:
- California Duck Curve (High Solar Penetration)
- Summer Heatwave & Scarcity Price Spikes
- Winter Heating Dual-Peak (Morning & Evening)
- Renewable Curtailment / Negative Pricing Events
"""

import numpy as np


def _generate_market_texture(T, variation=0.5, seed=42):
    """
    Generates realistic, auto-correlated (AR-1) intra-day price fluctuations
    so wholesale prices reflect organic power grid volatility.
    """
    if variation <= 1e-4:
        return np.zeros(T)
    rng = np.random.default_rng(seed)
    noise = np.zeros(T)
    ar = 0.65
    for t in range(1, T):
        noise[t] = ar * noise[t - 1] + np.sqrt(1.0 - ar**2) * rng.normal(0.0, 1.0)
    return noise * (7.0 * variation)


def generate_duck_curve(T=48, base_price=35.0, variation=0.5, seed=42):
    """
    Simulates a solar-dominated grid (CAISO 'duck curve') with multi-day weather evolution:
    - Day 1: Classic spring baseline (moderate solar depression, sharp evening ramp).
    - Day 2: Clear-sky high solar irradiance (deep zero-dollar midday belly, severe 8 PM peak).
    - Day 3: Passing cloud cover (shallower midday dip, higher morning bump, earlier evening peak).
    """
    prices = np.zeros(T)
    texture = _generate_market_texture(T, variation, seed=seed)
    for t in range(T):
        d = t // 24
        h = t % 24
        cycle = d % 3

        if cycle == 0:
            # Day 1: Standard spring solar curve
            base = base_price + 1.0
            solar_dip = -26.0 * np.exp(-0.5 * ((h - 13.0) / 2.0) ** 2)
            morning_bump = 16.0 * np.exp(-0.5 * ((h - 7.5) / 1.5) ** 2)
            evening_peak = 68.0 * np.exp(-0.5 * ((h - 19.5) / 1.8) ** 2)
            night_slack = 4.0 * np.sin(2 * np.pi * h / 24.0)
        elif cycle == 1:
            # Day 2: Severe solar depression & steep evening ramp (stricter net-load ramp)
            base = base_price - 4.0 * variation
            solar_dip = -(28.0 + 10.0 * variation) * np.exp(-0.5 * ((h - 12.5) / 2.2) ** 2)
            morning_bump = (14.0 - 4.0 * variation) * np.exp(-0.5 * ((h - 7.0) / 1.4) ** 2)
            evening_peak = (72.0 + 38.0 * variation) * np.exp(-0.5 * ((h - 20.0) / 1.9) ** 2)
            night_slack = 2.0 * np.sin(2 * np.pi * (h - 2) / 24.0)
        else:
            # Day 3: Passing clouds (less solar, higher morning load, earlier peak)
            base = base_price + 6.0 * variation
            solar_dip = -(18.0 - 6.0 * variation) * np.exp(-0.5 * ((h - 13.5) / 1.7) ** 2)
            morning_bump = (22.0 + 6.0 * variation) * np.exp(-0.5 * ((h - 8.0) / 1.6) ** 2)
            evening_peak = (64.0 + 18.0 * variation) * np.exp(-0.5 * ((h - 19.0) / 1.7) ** 2)
            night_slack = 5.0 * np.cos(2 * np.pi * h / 24.0)

        prices[t] = max(2.0, base + solar_dip + morning_bump + evening_peak + night_slack + texture[t])
    return prices


def generate_heatwave_spikes(T=48, base_price=42.0, variation=0.5, seed=42):
    """
    Simulates summer heatwave with shifting meteorological severity:
    - Day 1: Warm day with strong afternoon air conditioning demand (peak ~$160/MWh).
    - Day 2: Critical heat dome emergency with extreme scarcity pricing (spikes > $300/MWh).
    - Day 3: Persistent heatwave with elevated morning base and double afternoon spikes.
    """
    prices = np.zeros(T)
    texture = _generate_market_texture(T, variation, seed=seed + 10)
    for t in range(T):
        d = t // 24
        h = t % 24
        cycle = d % 3

        if cycle == 0:
            base = base_price
            temp_effect = 22.0 * np.sin((h - 8.0) * np.pi / 12.0) if 8 <= h <= 22 else -8.0
            spike = 125.0 if 16 <= h <= 18 else (45.0 if 14 <= h <= 19 else 0.0)
        elif cycle == 1:
            # Day 2: Extreme peak heat dome alert
            base = base_price + 10.0 * variation
            temp_effect = 32.0 * np.sin((h - 7.5) * np.pi / 12.0) if 7 <= h <= 23 else 0.0
            if 16 <= h <= 18:
                spike = 220.0 + 70.0 * variation + (25.0 if h == 17 else 0.0)
            elif 14 <= h <= 19:
                spike = 85.0 + 20.0 * variation
            else:
                spike = 0.0
        else:
            # Day 3: Sustained heat with double peaks
            base = base_price + 4.0 * variation
            temp_effect = 26.0 * np.sin((h - 8.0) * np.pi / 12.0) if 8 <= h <= 22 else -6.0
            if h in (15, 16):
                spike = 160.0 + 30.0 * variation
            elif h in (18, 19):
                spike = 140.0 + 25.0 * variation
            elif 14 <= h <= 20:
                spike = 55.0
            else:
                spike = 0.0

        prices[t] = max(15.0, base + temp_effect + spike + texture[t])
    return prices


def generate_winter_dual_peak(T=48, base_price=38.0, variation=0.5, seed=42):
    """
    Simulates winter electric heating dynamics with weather front transitions:
    - Day 1: Typical winter profile with balanced morning (8 AM) and evening (7 PM) peaks.
    - Day 2: Polar vortex morning freeze (massive morning super-peak ~$135/MWh, higher base).
    - Day 3: High-wind day with overnight wind surplus crashing prices, followed by sharp evening peak.
    """
    prices = np.zeros(T)
    texture = _generate_market_texture(T, variation, seed=seed + 20)
    for t in range(T):
        d = t // 24
        h = t % 24
        cycle = d % 3

        if cycle == 0:
            base = base_price
            morning = 52.0 * np.exp(-0.5 * ((h - 8.0) / 1.5) ** 2)
            evening = 62.0 * np.exp(-0.5 * ((h - 19.0) / 1.8) ** 2)
            midday = 8.0 * np.exp(-0.5 * ((h - 13.0) / 3.0) ** 2)
            night = -14.0 * np.exp(-0.5 * ((h - 3.5) / 2.0) ** 2)
        elif cycle == 1:
            # Day 2: Freezing cold snap morning
            base = base_price + 8.0 * variation
            morning = (75.0 + 25.0 * variation) * np.exp(-0.5 * ((h - 7.5) / 1.6) ** 2)
            evening = (58.0 + 10.0 * variation) * np.exp(-0.5 * ((h - 18.5) / 1.7) ** 2)
            midday = 18.0 * np.exp(-0.5 * ((h - 13.0) / 3.0) ** 2)
            night = -5.0 * np.exp(-0.5 * ((h - 3.5) / 2.0) ** 2)
        else:
            # Day 3: Wind-driven nocturnal drop and late evening rebound
            base = base_price - 4.0 * variation
            morning = (40.0 - 10.0 * variation) * np.exp(-0.5 * ((h - 8.5) / 1.4) ** 2)
            evening = (75.0 + 20.0 * variation) * np.exp(-0.5 * ((h - 19.5) / 1.9) ** 2)
            midday = 5.0 * np.exp(-0.5 * ((h - 13.5) / 2.5) ** 2)
            night = -(22.0 + 6.0 * variation) * np.exp(-0.5 * ((h - 3.0) / 2.2) ** 2)

        prices[t] = max(8.0, base + morning + evening + midday + night + texture[t])
    return prices


def generate_negative_pricing(T=48, base_price=28.0, variation=0.5, seed=42):
    """
    Simulates renewable curtailment and transmission congestion events:
    - Day 1: Classic midday solar overgeneration (negative prices 11 AM - 3 PM down to -$15/MWh).
    - Day 2: Extreme combined wind/solar glut (prolonged negative pricing down to -$32/MWh).
    - Day 3: Overnight nocturnal wind curtailment (negative from 1-4 AM) plus afternoon solar dip.
    """
    prices = np.zeros(T)
    texture = _generate_market_texture(T, variation, seed=seed + 30)
    for t in range(T):
        d = t // 24
        h = t % 24
        cycle = d % 3

        if cycle == 0:
            base = base_price
            curtail = -44.0 * np.exp(-0.5 * ((h - 13.0) / 1.8) ** 2)
            evening = 78.0 * np.exp(-0.5 * ((h - 20.0) / 2.2) ** 2)
            night = 0.0
        elif cycle == 1:
            # Day 2: Deep multi-hour renewable glut
            base = base_price - 4.0 * variation
            curtail = -(50.0 + 18.0 * variation) * np.exp(-0.5 * ((h - 12.5) / 2.4) ** 2)
            evening = (85.0 + 25.0 * variation) * np.exp(-0.5 * ((h - 20.5) / 2.0) ** 2)
            night = -4.0 * variation * np.exp(-0.5 * ((h - 2.0) / 2.0) ** 2)
        else:
            # Day 3: Night wind curtailment event + secondary solar dip
            base = base_price + 2.0 * variation
            curtail = -(36.0 - 8.0 * variation) * np.exp(-0.5 * ((h - 13.0) / 1.6) ** 2)
            evening = (72.0 + 12.0 * variation) * np.exp(-0.5 * ((h - 19.5) / 2.1) ** 2)
            night = -(30.0 + 8.0 * variation) * np.exp(-0.5 * ((h - 2.5) / 1.8) ** 2)

        prices[t] = base + curtail + evening + night + texture[t]
    return prices


SCENARIO_MAP = {
    "California Duck Curve (High Solar)": generate_duck_curve,
    "Summer Heatwave & Scarcity Spikes": generate_heatwave_spikes,
    "Winter Heating (Dual Peak)": generate_winter_dual_peak,
    "Renewable Curtailment (Negative Prices)": generate_negative_pricing,
}

SCENARIO_DESCRIPTIONS = {
    "California Duck Curve (High Solar)": (
        "Midday price depression (down to $2-$10/MWh) caused by massive solar PV feed-in, "
        "followed by a steep evening ramp to $110-$135/MWh as solar drops off and residential load surges. "
        "Each day exhibits realistic weather shifts in irradiance and peak ramp timing."
    ),
    "Summer Heatwave & Scarcity Spikes": (
        "Severe afternoon price spikes ($160-$330/MWh) driven by extreme air-conditioning cooling demand. "
        "Demonstrates day-over-day temperature escalation and peak heat-dome alert conditions."
    ),
    "Winter Heating (Dual Peak)": (
        "Two daily commercial and heating peaks: morning commute (7-9 AM) and evening lighting/heating (6-8 PM). "
        "Features freezing cold snaps and nocturnal wind shifts causing dynamic day-to-day contrast."
    ),
    "Renewable Curtailment (Negative Prices)": (
        "Deep negative prices (down to -$32/MWh) during solar/wind overgeneration. "
        "The battery earns revenue by soaking up grid congestion across varying day-to-day curtailment windows."
    ),
}


def get_scenario_prices(scenario_name, T=48, variation=0.5, seed=42):
    func = SCENARIO_MAP.get(scenario_name, generate_duck_curve)
    return func(T, variation=variation, seed=seed)


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
