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
    .highlight-rhs {
        background-color: rgba(59, 130, 246, 0.15);
        border-left: 4px solid #3B82F6;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 12px 0;
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
    "Interactive **Rolling Horizon & Sequential RHS Update** Simulator based on "
    "Warren Powell's *Sequential Decision Analytics*."
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

terminal_mode_label = st.sidebar.selectbox(
    "Terminal SOC Policy",
    [
        "Free (Unconstrained profit maximization)",
        "Cyclic (Reserve energy: SOC_end >= SOC_initial)",
        "Target Level (SOC_end >= 50% capacity)",
    ],
    index=0,
    help="Boundary condition enforced at the end of the look-ahead horizon.",
)
terminal_mode_key = "free"
if "Cyclic" in terminal_mode_label:
    terminal_mode_key = "cyclic_initial"
elif "Target" in terminal_mode_label:
    terminal_mode_key = "target_frac"

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

prices = get_scenario_prices(scenario_name, T=total_hours)
initial_soc_mwh = capacity_mwh * (initial_soc_pct / 100.0)

sim_res = simulate_rolling_horizon(
    battery=battery,
    price_profile=prices,
    initial_soc_mwh=initial_soc_mwh,
    horizon=lookahead_horizon,
    terminal_mode=terminal_mode_key,
    terminal_target_frac=0.50,
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

# Scenario Description Callout
st.info(f"💡 **Market Context**: {SCENARIO_DESCRIPTIONS[scenario_name]}")

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
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📈 Rolling Horizon Dispatch",
        "🔄 Sequential RHS Update Explorer",
        "⚖️ Parameter Sensitivity & Comparison",
        "📘 Mathematical Mechanics & Theory",
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

    fig.update_yaxes(title_text="Dispatch Power (MW)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Wholesale Price ($/MWh)", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Stored Energy (MWh)", row=2, col=1)
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
# TAB 2: Sequential RHS Update Explorer (The Core Educational Feature)
# ------------------------------------------------------------------------------
with tab2:
    st.subheader("🔍 Inside the Sequential Loop: The In-Place RHS Update")
    st.markdown(
        """
        In sequential decision analytics, the optimization matrix $A$ representing the battery physics 
        **never changes**. What changes at each hour $t$ is the **Right-Hand Side (RHS)** value of the initial state constraint:
        $$SOC_1 - \eta_c p_{c,1} + \frac{1}{\eta_d} p_{d,1} = \mathbf{S_t}$$
        where $\mathbf{S_t}$ is the battery's physical State of Charge at the beginning of hour $t$.
        """
    )

    inspect_t = st.slider(
        "Select Decision Hour (t) to Inspect",
        min_value=0,
        max_value=total_hours - 1,
        value=min(8, total_hours - 1),
        step=1,
        help="Explore the exact state, RHS pointer, and look-ahead plan solved at this step.",
    )

    plan = sim_res["lookahead_plans"][inspect_t]
    current_rhs_val = plan["current_soc_rhs"]
    window_len = len(plan["forecast_prices"])
    window_x = [inspect_t + tau for tau in range(window_len)]

    # Highlight RHS card
    st.markdown(
        f"""
        <div class="highlight-rhs">
            <h4 style="margin:0 0 6px 0; color:#38BDF8;">⚡ Hour t = {inspect_t} Optimization State</h4>
            <div><b>Physical State (Updated RHS):</b> <span style="font-size:1.15rem; color:#F59E0B; font-weight:700;">{current_rhs_val:.2f} MWh</span> ({current_rhs_val/battery.capacity_mwh*100:.1f}% SOC)</div>
            <div><b>RHS Equality Constraint Mutated in Solver:</b> <code>soc[0] - {battery.eta_c:.3f}*p_c[0] + {1.0/battery.eta_d:.3f}*p_d[0] == <b>{current_rhs_val:.2f}</b></code></div>
            <div><b>Committed Decision (Implemented for Hour {inspect_t}):</b> 
                Charge = <b>{sim_res['realized_pc'][inspect_t]:.1f} MW</b> | 
                Discharge = <b>{sim_res['realized_pd'][inspect_t]:.1f} MW</b> | 
                Step Profit = <b>${sim_res['step_profits'][inspect_t]:.2f}</b>
            </div>
            <div><b>Solver Execution Time:</b> <code>{plan['solve_time_ms']:.3f} ms</code> (Zero AML matrix re-allocation!)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Chart: History vs Lookahead Plan
    fig_step = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            f"Hour {inspect_t}: Look-Ahead Dispatch Plan vs Realized Past",
            f"Hour {inspect_t}: Look-Ahead SOC Trajectory Plan vs Realized Past",
        ),
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )

    # 1. Past Realized Dispatch
    if inspect_t > 0:
        past_x = list(range(inspect_t))
        fig_step.add_trace(
            go.Bar(
                x=past_x,
                y=sim_res["realized_pd"][:inspect_t],
                name="Past Discharge (MW)",
                marker_color="rgba(245, 158, 11, 0.4)",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
        fig_step.add_trace(
            go.Bar(
                x=past_x,
                y=-sim_res["realized_pc"][:inspect_t],
                name="Past Charge (MW)",
                marker_color="rgba(16, 185, 129, 0.4)",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )

    # 2. Implemented Decision at Hour inspect_t
    fig_step.add_trace(
        go.Bar(
            x=[inspect_t],
            y=[sim_res["realized_pd"][inspect_t]],
            name="Committed Discharge (t)",
            marker_color="#F59E0B",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig_step.add_trace(
        go.Bar(
            x=[inspect_t],
            y=[-sim_res["realized_pc"][inspect_t]],
            name="Committed Charge (t)",
            marker_color="#10B981",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )

    # 3. Look-Ahead Planned Dispatch (Future steps beyond inspect_t)
    if window_len > 1:
        future_x = window_x[1:]
        fig_step.add_trace(
            go.Scatter(
                x=future_x,
                y=plan["planned_pd"][1:],
                name="Look-Ahead Planned Discharge (Ghost)",
                line=dict(color="#F59E0B", dash="dash", width=2),
                mode="lines+markers",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
        fig_step.add_trace(
            go.Scatter(
                x=future_x,
                y=-plan["planned_pc"][1:],
                name="Look-Ahead Planned Charge (Ghost)",
                line=dict(color="#10B981", dash="dash", width=2),
                mode="lines+markers",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )

    # Look-ahead forecast price
    fig_step.add_trace(
        go.Scatter(
            x=window_x,
            y=plan["forecast_prices"],
            name="Look-Ahead Price Forecast",
            line=dict(color="#8B5CF6", width=2),
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    # 4. SOC Plot: Past Realized SOC vs Look-Ahead Planned SOC
    past_soc_x = list(range(inspect_t + 1))
    fig_step.add_trace(
        go.Scatter(
            x=past_soc_x,
            y=sim_res["realized_soc"][: inspect_t + 1],
            name="Realized Past SOC",
            line=dict(color="#06B6D4", width=3),
        ),
        row=2,
        col=1,
    )

    # Current step RHS dot
    fig_step.add_trace(
        go.Scatter(
            x=[inspect_t],
            y=[current_rhs_val],
            mode="markers+text",
            name="Current State S_t (RHS)",
            marker=dict(size=14, color="#F59E0B", symbol="star"),
            text=[f"RHS: {current_rhs_val:.1f} MWh"],
            textposition="top center",
        ),
        row=2,
        col=1,
    )

    # Planned SOC trajectory over window
    planned_soc_x = [inspect_t + tau for tau in range(window_len)]
    fig_step.add_trace(
        go.Scatter(
            x=planned_soc_x,
            y=plan["planned_soc"],
            name="Planned SOC Trajectory (Look-Ahead)",
            line=dict(color="#38BDF8", dash="dash", width=2.5),
            mode="lines+markers",
        ),
        row=2,
        col=1,
    )

    # Look-Ahead Window Shading
    fig_step.add_vrect(
        x0=inspect_t,
        x1=min(inspect_t + window_len, total_hours),
        fillcolor="rgba(59, 130, 246, 0.08)",
        layer="below",
        line_width=1,
        line_dash="dot",
        line_color="#3B82F6",
        annotation_text="Look-Ahead Horizon Window",
        annotation_position="top left",
        row=1,
        col=1,
    )

    fig_step.update_layout(
        template="plotly_dark",
        height=580,
        margin=dict(l=40, r=40, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1),
    )
    fig_step.update_yaxes(title_text="Dispatch (MW)", row=1, col=1, secondary_y=False)
    fig_step.update_yaxes(title_text="Price ($/MWh)", row=1, col=1, secondary_y=True)
    fig_step.update_yaxes(title_text="SOC (MWh)", row=2, col=1)
    fig_step.update_xaxes(title_text="Hour", row=2, col=1)

    st.plotly_chart(fig_step, use_container_width=True)

    st.markdown(
        """
        > **Key Takeaway**: Notice how the model planned ahead for the entire dashed window, but 
        > the simulation **only commits step t**! At hour $t+1$, a new price forecast arrives, 
        > the actual physical state becomes the new RHS, and the model re-optimizes. That is 
        > the essence of Model Predictive Control / Rolling Horizon sequential optimization.
        """
    )


# ------------------------------------------------------------------------------
# TAB 3: Parameter Sensitivity & Comparison
# ------------------------------------------------------------------------------
with tab3:
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
                terminal_mode=terminal_mode_key,
                terminal_target_frac=0.50,
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
                terminal_mode=terminal_mode_key,
                terminal_target_frac=0.50,
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
                terminal_mode=terminal_mode_key,
                terminal_target_frac=0.50,
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
                terminal_mode=terminal_mode_key,
                terminal_target_frac=0.50,
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
# TAB 4: Mathematical Mechanics & Theory
# ------------------------------------------------------------------------------
with tab4:
    st.subheader("📘 Sequential Decision Analytics: The 5 Elements & RHS Updates")
    st.markdown(
        r"""
        This application implements the canonical framework for **Sequential Decision Analytics (SDA)** 
        formalized by **Prof. Warren Powell** (*Sequential Decision Analytics and Modeling*, Princeton University).

        ---

        ### 1. The 5 Core Elements of Powell's Framework
        Every sequential optimization problem is characterized by five fundamental components:

        1. **State Variable ($S_t$)**:
           The physical state of the battery at time $t$:
           $$S_t = SOC_t \in [SOC_{min}, SOC_{max}]$$
           plus the updated market price information and forecasts.

        2. **Decision Variable ($x_t$)**:
           The actions taken at time step $t$:
           $$x_t = (p_{c,t}, p_{d,t}) \ge 0$$
           subject to power ratings $p_{c,t} \le P_{max}$ and $p_{d,t} \le P_{max}$.

        3. **Exogenous Information ($W_{t+1}$)**:
           Information that arrives between $t$ and $t+1$ (e.g., realized wholesale electricity price $\lambda_t$, revised solar/wind generation, forecast adjustments).

        4. **Transition Function ($S_{t+1} = f(S_t, x_t, W_{t+1})$)**:
           The physical energy conservation equation:
           $$S_{t+1} = S_t + \eta_c \Delta t \cdot p_{c,t} - rac{\Delta t}{\eta_d} p_{d,t}$$

        5. **Objective Function / Contribution ($C(S_t, x_t)$)**:
           The instantaneous financial margin realized at step $t$:
           $$C(S_t, x_t) = \lambda_t \cdot (p_{d,t} - p_{c,t}) - c_{deg} \cdot p_{d,t}$$

        ---

        ### 2. Direct Look-Ahead (DLA) Policy & Rolling Horizon
        At each hour $t$, we solve a Direct Look-Ahead linear program over horizon $H$:
        $$
        \max_{\{p_c, p_d, soc\}} \sum_{	au=1}^H \left[ (\lambda_{t+	au-1|t} - c_{deg}) p_{d,	au} - (\lambda_{t+	au-1|t} + c_{deg}) p_{c,	au} ight] \Delta t
        $$
        subject to:
        $$
        egin{aligned}
        	ext{Row 1 (The RHS Update!):} \quad & soc_1 - \eta_c p_{c,1} + rac{1}{\eta_d} p_{d,1} = \mathbf{S_t} \
        	ext{Rows } 2 \dots H: \quad & soc_	au - soc_{	au-1} - \eta_c p_{c,	au} + rac{1}{\eta_d} p_{d,	au} = 0 \
        	ext{Bounds:} \quad & 0 \le p_{c,	au} \le P_{max}, \quad 0 \le p_{d,	au} \le P_{max} \
        & SOC_{min} \le soc_	au \le SOC_{max}
        \end{aligned}
        $$

        ---

        ### 3. Why In-Place RHS Updating is Crucial in Production
        In standard naive code, developers rebuild the optimization model from scratch at every step $t$. 
        This re-allocates memory, regenerates thousands of AML AST object nodes, and forces the solver into a cold start.

        By contrast, the **Persistent RHS Approach**:
        - Keeps the constraint matrix $A_{eq}$ loaded in solver memory.
        - Mutates pointer $b_{eq}[0] = S_t$ in-place (a few nanoseconds).
        - Allows solvers (like HiGHS, Gurobi, or CPLEX) to perform **Dual Simplex Warm Starts**, solving subsequent steps in microsecond speed!
        """
    )
