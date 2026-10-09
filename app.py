import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from model import BatteryParameters, simulate_rolling_horizon
from scenarios import (
    SCENARIO_MAP,
    SCENARIO_DESCRIPTIONS,
    get_scenario_prices,
)

# ------------------------------------------------------------------------------
# Page Configuration & Custom CSS Styling
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Battery Storage Sequential Optimization",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Metric Card Styling */
    .metric-card {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.8));
        border: 1px solid rgba(148, 163, 184, 0.15);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        backdrop-filter: blur(8px);
    }
    .metric-label {
        font-size: 0.82rem;
        color: #94A3B8;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.65rem;
        font-weight: 700;
        color: #F8FAFC;
        line-height: 1.2;
    }
    .metric-sub {
        font-size: 0.78rem;
        color: #38BDF8;
        margin-top: 4px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 18px;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------------
# Sidebar Controls & Parameters
# ------------------------------------------------------------------------------
st.sidebar.title("⚡ Battery Optimizer")
st.sidebar.markdown(
    "Interactive **Rolling Horizon & Sequential RHS Update** Simulator"
)

st.sidebar.header("1. Market Scenario & Horizon")
scenario_name = st.sidebar.selectbox(
    "Wholesale Price Profile",
    list(SCENARIO_MAP.keys()),
    index=0,
    help="Select the wholesale electricity price dynamics.",
)

sim_days = st.sidebar.radio(
    "Simulation Duration",
    [1, 2, 3],
    index=1,
    format_func=lambda d: f"{d} Day{'s' if d > 1 else ''} ({d*24} Hours)",
    horizontal=True,
)
total_hours = sim_days * 24

price_variation = st.sidebar.slider(
    "Day-to-Day Price Variation",
    min_value=0.0,
    max_value=1.0,
    value=0.5,
    step=0.1,
    help="Controls the magnitude of day-to-day weather divergence and market price volatility.",
)

st.sidebar.header("2. Initial State & Rolling Horizon")

# HIGHLIGHTED PARAMETER: Initial SOC
initial_soc_pct = st.sidebar.slider(
    "Initial Battery SOC (%)",
    min_value=10,
    max_value=90,
    value=50,
    step=5,
    help=(
        "The starting energy level of the battery at t=0. "
        "This sets the initial Right-Hand Side (RHS) of the energy balance constraint. "
        "At subsequent steps, the RHS mutates in-place to the newly realized state S_t."
    ),
)

col_p1, col_p2, col_p3 = st.sidebar.columns(3)
if col_p1.button("10% (Low)"):
    initial_soc_pct = 10
if col_p2.button("50% (Mid)"):
    initial_soc_pct = 50
if col_p3.button("90% (High)"):
    initial_soc_pct = 90

lookahead_horizon = st.sidebar.slider(
    "Look-Ahead Horizon H (Hours)",
    min_value=4,
    max_value=36,
    value=24,
    step=2,
    help=(
        "Number of hours the optimizer looks ahead at each step t. "
        "Short horizons (e.g., 6h) exhibit myopic behavior, while longer horizons (24h) plan globally."
    ),
)

st.sidebar.header("3. Battery Specifications")
capacity_mwh = st.sidebar.number_input(
    "Storage Capacity (MWh)",
    min_value=10.0,
    max_value=500.0,
    value=100.0,
    step=25.0,
)

p_max_mw = st.sidebar.number_input(
    "Max Power Rating P_max (MW)",
    min_value=5.0,
    max_value=200.0,
    value=25.0,
    step=5.0,
    help="Charge and discharge power limit. Capacity / P_max defines storage duration.",
)

duration_hrs = capacity_mwh / p_max_mw if p_max_mw > 0 else 0
st.sidebar.caption(f"🔋 System Duration: **{duration_hrs:.1f} Hours** (C-rate: {p_max_mw/capacity_mwh:.2f} C)")

efficiency_pct = st.sidebar.slider(
    "Round-Trip Efficiency (%)",
    min_value=70,
    max_value=98,
    value=90,
    step=1,
    help="Total AC-AC roundtrip efficiency. Charging & discharging efficiencies are sqrt(eta_rt).",
)
eta_one_way = np.sqrt(efficiency_pct / 100.0)

degradation_cost = st.sidebar.slider(
    "Cell Degradation Cost ($/MWh)",
    min_value=0.0,
    max_value=40.0,
    value=0.0,
    step=2.5,
    help="Marginal wear-and-tear cost per MWh discharged. Acts as a threshold deadband on arbitrage spreads.",
)

forecast_noise = st.sidebar.slider(
    "Price Forecast Uncertainty (Noise Std $/MWh)",
    min_value=0.0,
    max_value=25.0,
    value=0.0,
    step=2.5,
    help="Adds forecast error to future look-ahead hours, demonstrating sequential adaptation.",
)

# ------------------------------------------------------------------------------
# Model Simulation Execution
# ------------------------------------------------------------------------------
battery = BatteryParameters(
    capacity_mwh=capacity_mwh,
    p_max_mw=p_max_mw,
    eta_c=eta_one_way,
    eta_d=eta_one_way,
    soc_min_frac=0.10,
    soc_max_frac=0.90,
    degradation_cost_per_mwh=degradation_cost,
)

prices = get_scenario_prices(scenario_name, T=total_hours, variation=price_variation)
initial_soc_mwh = capacity_mwh * (initial_soc_pct / 100.0)

sim_res = simulate_rolling_horizon(
    battery=battery,
    price_profile=prices,
    initial_soc_mwh=initial_soc_mwh,
    horizon=lookahead_horizon,
    forecast_noise_std=forecast_noise,
    seed=42,
)

# ------------------------------------------------------------------------------
# App Header & Overview
# ------------------------------------------------------------------------------
st.title("⚡ Sequential Battery Storage Optimization")
st.markdown(
    f"**Simulating Rolling Horizon Dispatch via Persistent In-Place RHS Updates** · "
    f"Market Scenario: *{scenario_name}* · Duration: *{total_hours} Hours*"
)

# # Scenario Description Callout
# st.info(f"💡 **Market Context**: {SCENARIO_DESCRIPTIONS[scenario_name]}")

# Top Metric Cards
mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)

with mcol1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Net Arbitrage Profit</div>
            <div class="metric-value">${sim_res['total_profit']:,.2f}</div>
            <div class="metric-sub">Rev: ${sim_res['total_revenue']:,.0f} | Cost: ${sim_res['total_cost']:,.0f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with mcol2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Full Battery Cycles</div>
            <div class="metric-value">{sim_res['full_cycles']:.2f} eq</div>
            <div class="metric-sub">Throughput: {sim_res['total_discharged_mwh']:.1f} MWh</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with mcol3:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Realized Spread</div>
            <div class="metric-value">${sim_res['realized_spread']:.2f}<span style="font-size:0.9rem">/MWh</span></div>
            <div class="metric-sub">Sell: ${sim_res['avg_discharge_price']:.1f} | Buy: ${sim_res['avg_charge_price']:.1f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with mcol4:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Roundtrip Loss</div>
            <div class="metric-value">{sim_res['efficiency_loss_mwh']:.1f} MWh</div>
            <div class="metric-sub">Efficiency: {efficiency_pct}% (AC-AC)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with mcol5:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Avg Solve Speed</div>
            <div class="metric-value">{sim_res['avg_solve_time_ms']:.2f} ms</div>
            <div class="metric-sub">In-Place HiGHS RHS Update</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")

# ------------------------------------------------------------------------------
# Main Content Tabs
# ------------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(
    [
        "📈 Rolling Horizon Dispatch",
        "⚖️ Parameter Sensitivity & Comparison",
        "📐 Optimization Model",
    ]
)

# ------------------------------------------------------------------------------
# TAB 1: Realized Rolling Horizon Dispatch
# ------------------------------------------------------------------------------
with tab1:
    st.subheader("Realized Battery Dispatch & State of Charge Schedule")
    st.markdown(
        "At each sequential hour $t$, the optimizer solves the forward look-ahead window, but only "
        "commits the first hour's decision. Below are the **actually realized** dispatch actions and physical SOC trajectory."
    )

    hours_x = list(range(total_hours))
    
    # Subplot with shared X axis
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.55, 0.45],
        subplot_titles=("Net Battery Dispatch (MW) & Wholesale Price ($/MWh)", "State of Charge Trajectory (MWh)"),
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )

    # Discharging (Positive MW) - Orange
    fig.add_trace(
        go.Bar(
            x=hours_x,
            y=sim_res["realized_pd"],
            name="Discharge (MW)",
            marker_color="#F59E0B",
            opacity=0.9,
            hovertemplate="Hour %{x}: Discharge %{y:.1f} MW<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )

    # Charging (Negative MW for bi-directional visual) - Green
    fig.add_trace(
        go.Bar(
            x=hours_x,
            y=-sim_res["realized_pc"],
            name="Charge (MW)",
            marker_color="#10B981",
            opacity=0.9,
            hovertemplate="Hour %{x}: Charge %{customdata:.1f} MW<extra></extra>",
            customdata=sim_res["realized_pc"],
        ),
        row=1,
        col=1,
        secondary_y=False,
    )

    # Price Curve on Secondary Y
    fig.add_trace(
        go.Scatter(
            x=hours_x,
            y=prices,
            name="Wholesale Price ($/MWh)",
            line=dict(color="#8B5CF6", width=2.5),
            hovertemplate="Hour %{x}: Price $%{y:.2f}/MWh<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    # Upper/Lower Max Power Guidelines
    fig.add_hline(y=battery.p_max_mw, line_dash="dot", line_color="rgba(245, 158, 11, 0.4)", row=1, col=1)
    fig.add_hline(y=-battery.p_max_mw, line_dash="dot", line_color="rgba(16, 185, 129, 0.4)", row=1, col=1)

    # SOC Trajectory
    soc_plot_x = list(range(total_hours + 1))
    fig.add_trace(
        go.Scatter(
            x=soc_plot_x,
            y=sim_res["realized_soc"],
            name="Battery SOC (MWh)",
            line=dict(color="#06B6D4", width=3),
            fill="tozeroy",
            fillcolor="rgba(6, 182, 212, 0.15)",
            hovertemplate="Step %{x}: SOC %{y:.1f} MWh<extra></extra>",
        ),
        row=2,
        col=1,
    )

    # Initial SOC marker
    fig.add_trace(
        go.Scatter(
            x=[0],
            y=[sim_res["realized_soc"][0]],
            mode="markers+text",
            name="Initial SOC",
            marker=dict(size=12, color="#3B82F6", symbol="diamond"),
            text=[f"SOC_0: {sim_res['realized_soc'][0]:.0f} MWh"],
            textposition="top right",
            hovertemplate="Initial SOC: %{y:.1f} MWh<extra></extra>",
        ),
        row=2,
        col=1,
    )

    # SOC Operating Limits (Shaded safe band)
    fig.add_hline(
        y=battery.soc_max_mwh,
        line_dash="dash",
        line_color="#EF4444",
        annotation_text=f"Max Safe SOC ({battery.soc_max_mwh:.0f} MWh)",
        row=2,
        col=1,
    )
    fig.add_hline(
        y=battery.soc_min_mwh,
        line_dash="dash",
        line_color="#EF4444",
        annotation_text=f"Min Safe SOC ({battery.soc_min_mwh:.0f} MWh)",
        row=2,
        col=1,
    )

    fig.update_layout(
        template="plotly_dark",
        height=620,
        margin=dict(l=40, r=40, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1),
        barmode="relative",
    )

    # Symmetrical zero-centered limits for both primary and secondary Y-axes
    p_lim = battery.p_max_mw * 1.15
    max_abs_price = max(float(np.max(np.abs(prices))), 10.0)
    price_lim = max_abs_price * 1.15

    fig.update_yaxes(
        title_text="Dispatch Power (MW)",
        range=[-p_lim, p_lim],
        zeroline=True,
        zerolinecolor="rgba(148, 163, 184, 0.35)",
        zerolinewidth=1.5,
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text="Wholesale Price ($/MWh)",
        range=[-price_lim, price_lim],
        zeroline=True,
        zerolinecolor="rgba(148, 163, 184, 0.35)",
        zerolinewidth=1.5,
        row=1,
        col=1,
        secondary_y=True,
    )
    fig.update_yaxes(
        title_text="Stored Energy (MWh)",
        range=[0, battery.capacity_mwh * 1.05],
        row=2,
        col=1,
    )
    fig.update_xaxes(title_text="Simulation Hour (t)", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)

    # Cumulative Revenue & Cash Flow Waterfall
    st.subheader("Financial Performance: Cumulative Cash Flow")
    fig_cash = go.Figure()
    fig_cash.add_trace(
        go.Scatter(
            x=hours_x,
            y=sim_res["cumulative_profits"],
            name="Cumulative Profit ($)",
            line=dict(color="#10B981", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(16, 185, 129, 0.1)",
            hovertemplate="Hour %{x}: Net Profit $%{y:,.2f}<extra></extra>",
        )
    )
    fig_cash.update_layout(
        template="plotly_dark",
        height=280,
        margin=dict(l=40, r=40, t=20, b=30),
        xaxis_title="Hour (t)",
        yaxis_title="Cumulative Net Arbitrage ($)",
    )
    st.plotly_chart(fig_cash, use_container_width=True)

    with st.expander("📋 View Realized Dispatch Data Table"):
        df_table = pd.DataFrame(
            {
                "Hour": hours_x,
                "Price ($/MWh)": np.round(prices, 2),
                "Charge (MW)": np.round(sim_res["realized_pc"], 2),
                "Discharge (MW)": np.round(sim_res["realized_pd"], 2),
                "End SOC (MWh)": np.round(sim_res["realized_soc"][1:], 2),
                "SOC (%)": np.round((sim_res["realized_soc"][1:] / battery.capacity_mwh) * 100, 1),
                "Revenue ($)": np.round(sim_res["step_revenues"], 2),
                "Cost ($)": np.round(sim_res["step_costs"], 2),
                "Net Profit ($)": np.round(sim_res["step_profits"], 2),
                "Cumulative ($)": np.round(sim_res["cumulative_profits"], 2),
                "Solve (ms)": np.round(sim_res["step_solve_times"], 2),
            }
        )
        st.dataframe(df_table, use_container_width=True)


# ------------------------------------------------------------------------------
# TAB 2: Parameter Sensitivity & Comparison
# ------------------------------------------------------------------------------
with tab2:
    st.subheader("⚖️ Parameter Sensitivity & Strategy Comparison")
    st.markdown(
        "Explore how key parameters dramatically shift battery arbitrage behavior, "
        "energy cycling, and total profitability."
    )

    comp_feature = st.selectbox(
        "Choose Parameter to Compare",
        [
            "Initial Battery SOC (10% vs 50% vs 90%)",
            "Look-Ahead Horizon Length (6 Hours Myopic vs 24 Hours Farsighted)",
            "Round-Trip Efficiency (80% vs 90% vs 96%)",
            "Degradation Cost ($0/MWh vs $15/MWh vs $30/MWh)",
        ],
    )

    if comp_feature.startswith("Initial Battery SOC"):
        st.markdown("#### Impact of Initial State of Charge ($SOC_0$)")
        st.markdown("How does starting empty vs starting full alter first-day arbitrage?")
        scenarios_to_run = [
            ("Low SOC (10%)", capacity_mwh * 0.10, "#EF4444"),
            ("Mid SOC (50%)", capacity_mwh * 0.50, "#06B6D4"),
            ("High SOC (90%)", capacity_mwh * 0.90, "#10B981"),
        ]

        fig_comp = go.Figure()
        summary_rows = []

        for name, init_val, color in scenarios_to_run:
            res_c = simulate_rolling_horizon(
                battery=battery,
                price_profile=prices,
                initial_soc_mwh=init_val,
                horizon=lookahead_horizon,
            )
            fig_comp.add_trace(
                go.Scatter(
                    x=list(range(total_hours + 1)),
                    y=res_c["realized_soc"],
                    name=f"{name} Trajectory",
                    line=dict(color=color, width=2.5),
                )
            )
            summary_rows.append(
                {
                    "Initial SOC Setup": name,
                    "Starting MWh": f"{init_val:.1f} MWh",
                    "Net Profit ($)": f"${res_c['total_profit']:,.2f}",
                    "Cycles Completed": f"{res_c['full_cycles']:.2f}",
                    "Avg Sale Price": f"${res_c['avg_discharge_price']:.2f}/MWh",
                    "Avg Buy Price": f"${res_c['avg_charge_price']:.2f}/MWh",
                    "Ending SOC": f"{res_c['realized_soc'][-1]:.1f} MWh",
                }
            )

        fig_comp.update_layout(
            template="plotly_dark",
            height=420,
            title="SOC Trajectories for Different Initial States (b_eq[0])",
            xaxis_title="Hour (t)",
            yaxis_title="Battery SOC (MWh)",
        )
        st.plotly_chart(fig_comp, use_container_width=True)
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

        st.info(
            "💡 **Observation**: When starting at **90% SOC**, the battery can immediately monetize early morning peak prices "
            "without needing to wait for a low-price charging valley. Conversely, when starting at **10% SOC**, the battery is constrained "
            "to charge first during night/solar hours before it can sell."
        )

    elif comp_feature.startswith("Look-Ahead Horizon Length"):
        st.markdown("#### Myopic (6h) vs Farsighted (24h) Optimization")
        st.markdown("Does a short look-ahead horizon cause the battery to sell too early and miss the true evening peak?")
        scenarios_to_run = [
            ("Myopic (6-Hour Horizon)", 6, "#EF4444"),
            ("Moderate (12-Hour Horizon)", 12, "#F59E0B"),
            ("Farsighted (24-Hour Horizon)", 24, "#10B981"),
        ]

        fig_comp = go.Figure()
        summary_rows = []

        for name, h_len, color in scenarios_to_run:
            res_c = simulate_rolling_horizon(
                battery=battery,
                price_profile=prices,
                initial_soc_mwh=initial_soc_mwh,
                horizon=h_len,
            )
            fig_comp.add_trace(
                go.Scatter(
                    x=list(range(total_hours)),
                    y=res_c["cumulative_profits"],
                    name=name,
                    line=dict(color=color, width=2.5),
                )
            )
            summary_rows.append(
                {
                    "Horizon": name,
                    "Net Profit ($)": f"${res_c['total_profit']:,.2f}",
                    "Cycles Completed": f"{res_c['full_cycles']:.2f}",
                    "Realized Spread": f"${res_c['realized_spread']:.2f}/MWh",
                    "Avg Solve Time (ms)": f"{res_c['avg_solve_time_ms']:.2f} ms",
                }
            )

        fig_comp.update_layout(
            template="plotly_dark",
            height=420,
            title="Cumulative Revenue Growth: Short vs Long Look-Ahead Horizon",
            xaxis_title="Hour (t)",
            yaxis_title="Cumulative Net Profit ($)",
        )
        st.plotly_chart(fig_comp, use_container_width=True)
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

        st.info(
            "💡 **Observation**: With a **6-hour horizon**, the battery suffers from myopic blindness. "
            "It charges during early morning and empties during a moderate 8 AM bump, leaving no room to capture the massive 7 PM evening super-peak!"
        )

    elif comp_feature.startswith("Round-Trip Efficiency"):
        st.markdown("#### Impact of Round-Trip Efficiency on Arbitrage Feasibility")
        scenarios_to_run = [
            ("75% Efficiency", 0.75, "#EF4444"),
            ("88% Efficiency", 0.88, "#F59E0B"),
            ("96% Efficiency", 0.96, "#10B981"),
        ]

        summary_rows = []
        for name, eff, color in scenarios_to_run:
            bat_c = BatteryParameters(
                capacity_mwh=capacity_mwh,
                p_max_mw=p_max_mw,
                eta_c=np.sqrt(eff),
                eta_d=np.sqrt(eff),
                soc_min_frac=0.10,
                soc_max_frac=0.90,
                degradation_cost_per_mwh=degradation_cost,
            )
            res_c = simulate_rolling_horizon(
                battery=bat_c,
                price_profile=prices,
                initial_soc_mwh=initial_soc_mwh,
                horizon=lookahead_horizon,
            )
            summary_rows.append(
                {
                    "Efficiency Level": name,
                    "Net Profit ($)": f"${res_c['total_profit']:,.2f}",
                    "Full Cycles": f"{res_c['full_cycles']:.2f}",
                    "Roundtrip Losses": f"{res_c['efficiency_loss_mwh']:.1f} MWh",
                    "Realized Spread": f"${res_c['realized_spread']:.2f}/MWh",
                }
            )
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    elif comp_feature.startswith("Degradation Cost"):
        st.markdown("#### Impact of Cell Cycling & Degradation Cost")
        scenarios_to_run = [
            ("Zero Wear ($0/MWh)", 0.0),
            ("Moderate ($15/MWh)", 15.0),
            ("High Wear ($30/MWh)", 30.0),
        ]

        summary_rows = []
        for name, deg in scenarios_to_run:
            bat_c = BatteryParameters(
                capacity_mwh=capacity_mwh,
                p_max_mw=p_max_mw,
                eta_c=eta_one_way,
                eta_d=eta_one_way,
                soc_min_frac=0.10,
                soc_max_frac=0.90,
                degradation_cost_per_mwh=deg,
            )
            res_c = simulate_rolling_horizon(
                battery=bat_c,
                price_profile=prices,
                initial_soc_mwh=initial_soc_mwh,
                horizon=lookahead_horizon,
            )
            summary_rows.append(
                {
                    "Degradation Setting": name,
                    "Net Profit ($)": f"${res_c['total_profit']:,.2f}",
                    "Cycles Completed": f"{res_c['full_cycles']:.2f}",
                    "Total Discharged": f"{res_c['total_discharged_mwh']:.1f} MWh",
                }
            )
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)


# ------------------------------------------------------------------------------
# TAB 3: Optimization Model Formulation
# ------------------------------------------------------------------------------
with tab3:
    st.subheader("📐 Battery Storage Optimization Model")
    st.markdown(
        r"""
        At each rolling decision hour $t$, the battery energy arbitrage problem is solved as a 
        **Direct Look-Ahead (DLA) Linear Program** over a forward horizon of $H$ hours ($\tau = 1, \dots, H$).
        """
    )

    st.markdown("#### 1. Mathematical Formulation")
    st.markdown(
        r"""
        **Decision Variables** (for each interval $\tau \in \{1, \dots, H\}$):
        - $p_{c,\tau} \ge 0$: Battery charging power (MW)
        - $p_{d,\tau} \ge 0$: Battery discharging power (MW)
        - $soc_\tau$: Battery State of Charge at the end of interval $\tau$ (MWh)

        ---

        **Objective Function:**
        $$\max_{\{p_c, p_d, soc\}} \sum_{\tau=1}^H \left[ \left(\mathbf{\lambda_{t+\tau-1|t}} - c_{\text{deg}}\right) p_{d,\tau} - \left(\mathbf{\lambda_{t+\tau-1|t}} + c_{\text{deg}}\right) p_{c,\tau} \right] \Delta t$$

        **Subject to Constraints:**
        $$
        \begin{aligned}
        \text{Initial Energy Balance } (\tau=1): \quad & soc_1 - \eta_c \Delta t \cdot p_{c,1} + \frac{\Delta t}{\eta_d} p_{d,1} = \mathbf{S_t} \\
        \text{Inter-Temporal Dynamics } (\tau = 2, \dots, H): \quad & soc_\tau - soc_{\tau-1} - \eta_c \Delta t \cdot p_{c,\tau} + \frac{\Delta t}{\eta_d} p_{d,\tau} = 0 \\
        \text{Power Capacity Bounds:} \quad & 0 \le p_{c,\tau} \le P_{\max}, \quad 0 \le p_{d,\tau} \le P_{\max}, \quad \forall \tau = 1, \dots, H \\
        \text{Storage Energy Bounds:} \quad & SOC_{\min} \le soc_\tau \le SOC_{\max}, \quad \forall \tau = 1, \dots, H
        \end{aligned}
        $$
        """
    )

    st.markdown("---")
    st.markdown("#### 2. Parameters Updated at Every Time Step ($t$)")
    st.markdown(
        "In the rolling horizon loop, the optimization model structure remains identical while only **two parameters mutate** at each hour:"
    )

    col_up1, col_up2 = st.columns(2)
    with col_up1:
        st.markdown(
            r"""
            <div class="metric-card" style="border-left: 4px solid #F59E0B; margin-bottom: 12px;">
                <div style="font-size:1.05rem; font-weight:700; color:#F59E0B; margin-bottom:6px;">
                    🔄 1. Physical State of Charge (RHS): <code>S_t</code>
                </div>
                <div style="font-size:0.9rem; color:#CBD5E1; line-height:1.5;">
                    <b>Location in Model:</b> Right-Hand Side (RHS) of the initial energy balance constraint (&tau; = 1).<br>
                    <b>Why it updates:</b> Reflects the battery's actually realized physical State of Charge at the start of hour <i>t</i> resulting from preceding dispatches.<br>
                    <b>Solver Action:</b> Mutates the RHS equality vector in-place: <code>b_eq[0] = S_t</code> (fast warm-start solve).
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_up2:
        st.markdown(
            r"""
            <div class="metric-card" style="border-left: 4px solid #38BDF8; margin-bottom: 12px;">
                <div style="font-size:1.05rem; font-weight:700; color:#38BDF8; margin-bottom:6px;">
                    🔄 2. Price Forecast Vector: <code>&lambda;_{t+&tau;-1|t}</code>
                </div>
                <div style="font-size:0.9rem; color:#CBD5E1; line-height:1.5;">
                    <b>Location in Model:</b> Linear objective function cost coefficient vector <code>c</code>.<br>
                    <b>Why it updates:</b> At each step <i>t</i>, the look-ahead horizon rolls forward [<i>t</i> &hellip; <i>t</i>+<i>H</i>-1], incorporating the latest market price forecast and resolving near-term uncertainty.<br>
                    <b>Solver Action:</b> Mutates the linear objective coefficients <code>c</code> for charging and discharging variables.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 8px; padding: 12px 16px; margin-top: 8px;">
            <span style="color: #94A3B8; font-weight: 600;">🔒 Structurally Invariant Elements (Unchanged Across All Steps):</span>
            <ul style="margin: 6px 0 0 0; color: #CBD5E1; font-size: 0.88rem;">
                <li><b>Constraint Matrix (A_eq):</b> Efficiency coefficients (&eta;_c, 1/&eta;_d) and conservation physics stay constant.</li>
                <li><b>Intermediate Equality RHS (b_eq[&tau; &gt; 1]):</b> Exactly 0 for all future look-ahead intervals.</li>
                <li><b>Decision Bounds:</b> Inverter limits [0, P_max] and energy bounds [SOC_min, SOC_max].</li>
                <li><b>Degradation Cost:</b> Battery cell wear cost per MWh (c_deg).</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
