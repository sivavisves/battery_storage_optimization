# Sequential Battery Storage Optimization ⚡

[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?style=flat&logo=streamlit)](https://streamlit.io)
[![HiGHS](https://img.shields.io/badge/Solver-HiGHS-blue?style=flat)](https://highs.dev)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python)](https://python.org)

An interactive **Streamlit** application featuring **Sequential Optimization and Rolling Horizon Dispatch** for battery storage systems. 

Based on **Prof. Warren Powell's** [*Sequential Decision Analytics (SDA)*](https://warrenpowell.org/sdam/) framework and recent research on [market-based storage dispatch](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5377300), this repository demonstrates how persistent models and **in-place Right-Hand Side (RHS) updates** empower real-time battery arbitrage under shifting market forecasts.

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

## 🏛️ Academic Foundation & References

This application builds upon and is inspired by the following literature:

- **Warren B. Powell**, [**Sequential Decision Analytics and Modeling: Modeling with Python**](https://warrenpowell.org/sdam/), Princeton University.
  - Formalizes sequential decision analytics (SDA), direct look-ahead (DLA) policies, state transition dynamics, and persistent rolling horizon formulations.

- **Siva Visvesvaran, Jacob Mays, and Kaleb Smith**, [**Market-based Storage Dispatch and Capacity Accreditation in Electricity Markets**](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5377300), *SSRN Working Paper No. 5377300*.
  - Analyzes market-based battery storage dispatch, rolling look-ahead optimization, price formation, and capacity value in modern electricity markets.

- **Model Predictive Control (MPC)** and rolling horizon mathematical programming in power systems.

<details>
<summary><b>BibTeX Citations</b></summary>

```bibtex
@book{powell2022sdam,
  title     = {Sequential Decision Analytics and Modeling: Modeling with Python},
  author    = {Powell, Warren B.},
  year      = {2022},
  url       = {https://warrenpowell.org/sdam/}
}

@article{visvesvaran2024market,
  title     = {Market-based Storage Dispatch and Capacity Accreditation in Electricity Markets},
  author    = {Visvesvaran, Siva and Mays, Jacob and Smith, Kaleb},
  journal   = {SSRN Electronic Journal},
  year      = {2024},
  doi       = {10.2139/ssrn.5377300},
  url       = {https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5377300}
}
```
</details>
