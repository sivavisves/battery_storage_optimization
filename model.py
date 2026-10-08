"""
Battery storage optimization engine using persistent LP formulation and in-place RHS updates.
Based on Warren Powell's Sequential Decision Analytics (SDA) and Rolling Horizon Dispatch.
"""

from dataclasses import dataclass
import time
import numpy as np
import scipy.optimize as opt


@dataclass
class BatteryParameters:
    capacity_mwh: float = 100.0        # Total energy capacity E_max (MWh)
    p_max_mw: float = 25.0              # Max charge/discharge power P_max (MW)
    eta_c: float = 0.95                 # Charging efficiency (e.g. 0.95)
    eta_d: float = 0.95                 # Discharging efficiency (e.g. 0.95)
    soc_min_frac: float = 0.10          # Minimum safe State of Charge (fraction)
    soc_max_frac: float = 0.90          # Maximum safe State of Charge (fraction)
    degradation_cost_per_mwh: float = 0.0  # Cell wear cost per MWh discharged ($/MWh)

    @property
    def soc_min_mwh(self) -> float:
        return self.capacity_mwh * self.soc_min_frac

    @property
    def soc_max_mwh(self) -> float:
        return self.capacity_mwh * self.soc_max_frac

    @property
    def usable_capacity_mwh(self) -> float:
        return self.soc_max_mwh - self.soc_min_mwh

    @property
    def round_trip_efficiency(self) -> float:
        return self.eta_c * self.eta_d

    @property
    def duration_hours(self) -> float:
        return self.capacity_mwh / self.p_max_mw if self.p_max_mw > 0 else 0.0


class PersistentBatteryLP:
    """
    Instantiates the optimization model constraint matrix A_eq ONCE outside the loop.
    At each sequential step t:
      - RHS vector b_eq[0] is mutated in-place to current_soc
      - Objective vector c is updated with latest price forecast
    Solves via SciPy's HiGHS simplex/interior-point backend.
    """

    def __init__(self, battery: BatteryParameters, horizon: int):
        self.battery = battery
        self.horizon = horizon

        # Decision variables per timestep tau in 0..horizon-1:
        # Index layout:
        # [0 .. H-1] : p_c (charging power MW)
        # [H .. 2H-1]: p_d (discharging power MW)
        # [2H .. 3H-1]: soc (State of Charge MWh at end of timestep)
        self.n_vars = 3 * horizon
        self.n_cons = horizon

        # Pre-allocate invariant constraint matrix A_eq
        self.A_eq = np.zeros((self.n_cons, self.n_vars), dtype=float)
        self.b_eq = np.zeros(self.n_cons, dtype=float)

        # Pre-allocate objective vector
        self.c = np.zeros(self.n_vars, dtype=float)

        # Bounds layout
        self.bounds = []
        # p_c bounds
        for _ in range(horizon):
            self.bounds.append((0.0, battery.p_max_mw))
        # p_d bounds
        for _ in range(horizon):
            self.bounds.append((0.0, battery.p_max_mw))
        # soc bounds
        for _ in range(horizon):
            self.bounds.append((battery.soc_min_mwh, battery.soc_max_mwh))

        self._build_static_structure()

    def _build_static_structure(self):
        H = self.horizon
        eta_c = self.battery.eta_c
        inv_eta_d = 1.0 / self.battery.eta_d

        # Row 0: soc[0] - eta_c * p_c[0] + (1/eta_d) * p_d[0] = current_soc (RHS)
        self.A_eq[0, 2 * H + 0] = 1.0
        self.A_eq[0, 0] = -eta_c
        self.A_eq[0, H + 0] = inv_eta_d

        # Rows 1 .. H-1: soc[tau] - soc[tau-1] - eta_c * p_c[tau] + (1/eta_d) * p_d[tau] = 0
        for tau in range(1, H):
            self.A_eq[tau, 2 * H + tau] = 1.0
            self.A_eq[tau, 2 * H + tau - 1] = -1.0
            self.A_eq[tau, tau] = -eta_c
            self.A_eq[tau, H + tau] = inv_eta_d
            self.b_eq[tau] = 0.0

    def solve_step(
        self,
        current_soc: float,
        price_forecast: np.ndarray,
        terminal_target_mwh: float = None,
    ):
        """
        Executes a single sequential solve:
          1. Mutates RHS pointer b_eq[0] = current_soc (In-Place RHS Update!)
          2. Mutates objective coefficients c for prices and degradation
          3. Solves linear program via HiGHS
        """
        H = len(price_forecast)
        t_start = time.perf_counter()

        # If look-ahead window is shorter than max horizon (near simulation end), slice arrays
        if H == self.horizon:
            A_eq = self.A_eq
            b_eq = self.b_eq
            c = self.c
            bounds = self.bounds
        else:
            # Sub-horizon slice
            A_eq = np.zeros((H, 3 * H), dtype=float)
            b_eq = np.zeros(H, dtype=float)
            c = np.zeros(3 * H, dtype=float)
            eta_c = self.battery.eta_c
            inv_eta_d = 1.0 / self.battery.eta_d

            A_eq[0, 2 * H + 0] = 1.0
            A_eq[0, 0] = -eta_c
            A_eq[0, H + 0] = inv_eta_d

            for tau in range(1, H):
                A_eq[tau, 2 * H + tau] = 1.0
                A_eq[tau, 2 * H + tau - 1] = -1.0
                A_eq[tau, tau] = -eta_c
                A_eq[tau, H + tau] = inv_eta_d

            bounds = (
                [(0.0, self.battery.p_max_mw)] * H
                + [(0.0, self.battery.p_max_mw)] * H
                + [(self.battery.soc_min_mwh, self.battery.soc_max_mwh)] * H
            )

        # IN-PLACE RHS UPDATE: The current physical state of the battery
        b_eq[0] = current_soc

        # Objective update (Minimization convention: Min sum(cost - rev))
        # c for p_c (charge): + price + degradation
        # c for p_d (discharge): - price + degradation
        deg = self.battery.degradation_cost_per_mwh
        for tau in range(H):
            c[tau] = price_forecast[tau] + deg
            c[H + tau] = -price_forecast[tau] + deg
            c[2 * H + tau] = 0.0

        # Optional Terminal SOC constraint: soc[H-1] >= terminal_target_mwh
        A_ub = None
        b_ub = None
        if terminal_target_mwh is not None:
            # -soc[H-1] <= -terminal_target_mwh
            A_ub = np.zeros((1, 3 * H), dtype=float)
            A_ub[0, 3 * H - 1] = -1.0
            b_ub = np.array([-terminal_target_mwh], dtype=float)

        # Solve with SciPy HiGHS backend
        res = opt.linprog(
            c=c,
            A_eq=A_eq,
            b_eq=b_eq,
            A_ub=A_ub,
            b_ub=b_ub,
            bounds=bounds,
            method="highs",
        )

        t_end = time.perf_counter()
        solve_time_ms = (t_end - t_start) * 1000.0

        if not res.success:
            # Fallback if unfeasible: idle
            return {
                "success": False,
                "solve_time_ms": solve_time_ms,
                "p_c": np.zeros(H),
                "p_d": np.zeros(H),
                "soc": np.full(H, current_soc),
                "message": res.message,
            }

        p_c_sol = res.x[0:H]
        p_d_sol = res.x[H : 2 * H]
        soc_sol = res.x[2 * H : 3 * H]

        return {
            "success": True,
            "solve_time_ms": solve_time_ms,
            "p_c": p_c_sol,
            "p_d": p_d_sol,
            "soc": soc_sol,
            "message": res.message,
        }


def simulate_rolling_horizon(
    battery: BatteryParameters,
    price_profile: np.ndarray,
    initial_soc_mwh: float,
    horizon: int = 24,
    terminal_mode: str = "free",
    terminal_target_frac: float = 0.50,
    forecast_noise_std: float = 0.0,
    seed: int = 42,
):
    """
    Executes the full sequential decision pipeline:
      At step t:
        1. Query current physical state S_t
        2. Receive look-ahead price forecast [t .. t+H-1]
        3. Mutate persistent LP RHS: b_eq[0] = S_t
        4. Solve LP to find optimal look-ahead plan
        5. Commit and execute ONLY first-hour dispatch (p_c[0], p_d[0])
        6. Transition physical state to S_{t+1} and realize economic cash flow
    """
    T = len(price_profile)
    rng = np.random.default_rng(seed)
    optimizer = PersistentBatteryLP(battery, horizon)

    current_soc = float(np.clip(initial_soc_mwh, battery.soc_min_mwh, battery.soc_max_mwh))

    # Recording history
    realized_pc = []
    realized_pd = []
    realized_soc = [current_soc]
    step_solve_times = []
    step_profits = []
    step_revenues = []
    step_costs = []
    lookahead_plans = []  # Stores (t, forecast_prices, planned_pc, planned_pd, planned_soc)

    total_profit = 0.0

    for t in range(T):
        window_len = min(horizon, T - t)
        true_window = price_profile[t : t + window_len]

        # Forecast with optional uncertainty
        if forecast_noise_std > 1e-4:
            forecast_prices = np.zeros(window_len)
            for tau in range(window_len):
                lead = np.sqrt(tau / max(1.0, float(horizon)))
                forecast_prices[tau] = true_window[tau] + rng.normal(0.0, forecast_noise_std * lead)
        else:
            forecast_prices = true_window.copy()

        # Determine terminal target condition
        terminal_target = None
        if terminal_mode == "cyclic_initial":
            terminal_target = initial_soc_mwh
        elif terminal_mode == "target_frac":
            terminal_target = battery.capacity_mwh * terminal_target_frac

        # Solve step via in-place RHS update
        sol = optimizer.solve_step(current_soc, forecast_prices, terminal_target)

        step_solve_times.append(sol["solve_time_ms"])

        # Extract immediate action (tau = 0)
        p_c_action = float(sol["p_c"][0])
        p_d_action = float(sol["p_d"][0])

        # Physical transition
        delta_energy = (battery.eta_c * p_c_action) - (p_d_action / battery.eta_d)
        next_soc = float(np.clip(current_soc + delta_energy, battery.soc_min_mwh, battery.soc_max_mwh))

        # Realized economic cash flow at actual wholesale price
        realized_price = float(price_profile[t])
        revenue = realized_price * p_d_action
        charging_cost = realized_price * p_c_action
        deg_cost = battery.degradation_cost_per_mwh * p_d_action
        net_step_profit = revenue - charging_cost - deg_cost

        realized_pc.append(p_c_action)
        realized_pd.append(p_d_action)
        realized_soc.append(next_soc)
        step_revenues.append(revenue)
        step_costs.append(charging_cost + deg_cost)
        step_profits.append(net_step_profit)
        total_profit += net_step_profit

        # Save look-ahead plan for interactive step inspection
        lookahead_plans.append({
            "t": t,
            "current_soc_rhs": current_soc,
            "forecast_prices": forecast_prices,
            "planned_pc": sol["p_c"],
            "planned_pd": sol["p_d"],
            "planned_soc": sol["soc"],
            "solve_time_ms": sol["solve_time_ms"],
        })

        # Advance state
        current_soc = next_soc

    # Aggregate metrics
    pc_arr = np.array(realized_pc)
    pd_arr = np.array(realized_pd)
    total_charged = float(np.sum(pc_arr))
    total_discharged = float(np.sum(pd_arr))

    total_revenue = float(np.sum(step_revenues))
    total_cost = float(np.sum(step_costs))

    avg_charge_price = float(np.sum(pc_arr * price_profile) / total_charged) if total_charged > 1e-4 else 0.0
    avg_discharge_price = float(np.sum(pd_arr * price_profile) / total_discharged) if total_discharged > 1e-4 else 0.0

    usable_cap = max(1.0, battery.usable_capacity_mwh)
    full_cycles = total_discharged / usable_cap
    efficiency_loss = total_charged - total_discharged

    return {
        "realized_pc": pc_arr,
        "realized_pd": pd_arr,
        "realized_soc": np.array(realized_soc),
        "step_profits": np.array(step_profits),
        "cumulative_profits": np.cumsum(step_profits),
        "step_revenues": np.array(step_revenues),
        "step_costs": np.array(step_costs),
        "step_solve_times": np.array(step_solve_times),
        "lookahead_plans": lookahead_plans,
        "total_profit": total_profit,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "total_charged_mwh": total_charged,
        "total_discharged_mwh": total_discharged,
        "full_cycles": full_cycles,
        "avg_charge_price": avg_charge_price,
        "avg_discharge_price": avg_discharge_price,
        "realized_spread": avg_discharge_price - avg_charge_price,
        "efficiency_loss_mwh": efficiency_loss,
        "avg_solve_time_ms": float(np.mean(step_solve_times)),
        "max_solve_time_ms": float(np.max(step_solve_times)),
    }
