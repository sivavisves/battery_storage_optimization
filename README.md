# Sequential Battery Storage Optimization ⚡

[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?style=flat&logo=streamlit)](https://streamlit.io)
[![HiGHS](https://img.shields.io/badge/Solver-HiGHS-blue?style=flat)](https://highs.dev)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python)](https://python.org)

An interactive **Streamlit** application featuring **Sequential Optimization and Rolling Horizon Dispatch** for battery storage systems. 

Based on **Prof. Warren Powell's** *Sequential Decision Analytics (SDA)* framework, this repository demonstrates how persistent models and **in-place Right-Hand Side (RHS) updates** empower real-time battery arbitrage under shifting market forecasts.

---

## 🎛️ Parameters You Can Play Around With in the App

| Parameter Category | Parameter | What It Controls & Why It's Interesting |
| :--- | :--- | :--- |
| **Initial State (Featured!)** | **Initial SOC ($SOC_0$)** | Sets the starting energy level (and the initial RHS $b[0]$). Starting empty (10%) forces the battery to charge first, whereas starting full (90%) lets it cash in on early morning price spikes! |
| **Look-Ahead Window** | **Horizon Length ($H$)** | Adjust from 4h to 36h. Demonstrates **myopic vs. farsighted arbitrage**: a 6h horizon sells too early for moderate peaks and misses evening super-peaks! |
| **Battery Sizing** | **Capacity & Power ($E_{max}, P_{max}$)** | Configures storage duration (e.g. 4-hour utility scale vs 2-hour peaker) and C-rate. |
| **Efficiency** | **Round-Trip Efficiency ($\eta_{rt}$)** | From 75% to 98%. Dictates the minimum arbitrage spread needed to overcome roundtrip losses. |
| **Battery Health** | **Degradation Cost ($/MWh)** | Cell cycling wear cost. Acts as an economic deadband, preventing the battery from cycling for tiny price spreads. |
| **Market Profiles** | **Wholesale Price Scenarios** | Test against California Duck Curve, Summer Heatwave Spikes, Winter Dual-Peak, and Negative Pricing! |
| **Market Volatility** | **Day-to-Day Price Variation** | Scale day-to-day weather divergence and intra-day wholesale price volatility across multi-day horizons. |
| **Information State** | **Forecast Uncertainty ($\sigma$)** | Introduces lead-time dependent noise to future hours, showcasing real-time sequential adaptation. |

---

## 🚀 Quickstart

### 1. Clone & Navigate
```bash
git clone <repo-url>
cd battery_storage_optimization
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Launch Streamlit Application
```bash
streamlit run app.py
```

---

## 📁 Repository Structure

```text
battery_storage_optimization/
├── app.py              # Main interactive Streamlit application with multi-tab dashboard
├── model.py            # Persistent LP optimization engine & rolling horizon simulator
├── scenarios.py        # Wholesale price scenario generators (Duck Curve, Heatwave, etc.)
├── requirements.txt    # Project dependencies
├── .gitignore          # Git ignore rules
└── README.md           # Documentation and academic background
```

---

## 🏛️ Academic Foundation

This application is inspired by:
- **Warren B. Powell**, *Sequential Decision Analytics and Modeling: Modeling with Python*, Princeton University.
- **Model Predictive Control (MPC)** and Rolling Horizon Dispatch in Power Systems.
