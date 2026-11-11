# LLMAgent_UDSControl

LLM-agent-assisted real-time control (RTC) for an urban drainage system in the Chaohu
basin, China. The project couples the SWMM hydraulic model with rule-based control (BC),
model predictive control (MPC), particle swarm optimization (PSO) and large language model
(LLM) agents, and evaluates every controller on the same rainfall events using the combined
flooding + combined-sewer-overflow (F+C) volume.

The core method, **AgenticAI-BC**, keeps the BC rule controller as the base policy and lets
an LLM relax the base actions (pumps can only be switched from off to on) when triggered by
a weather warning or by the realtime system state. If the LLM is not triggered, returns an
invalid response, or fails the timing validation, the controller falls back to the pure BC
action.

## Methods compared

| Method | Description | Implementation |
|---|---|---|
| BC (baseline) | Per-pump hysteresis water-level thresholds, no prediction or learning | `DRL-control/BC/BC.py`, `step1-BC-control/main_BCtest.py` |
| MPC | Receding-horizon control; PSO optimizes the next `Np` pump actions on SWMM predictions | `step2-MPC-control-best/main_MPCtest.py`, `pso.py` |
| AgenticAI-BC | BC + event-driven LLM adjustment with periodic refresh and timing validation | `step3-BCAgent-control/` (and `-GLM`, `-Kimi`, `-MiniMax` variants) |
| PPO / DirectAgent | Referenced by some result scripts but training code is **not included** in this snapshot | — |

All methods are evaluated with the same events, SWMM model and control step.

## Workflow

| Stage | Script | Purpose |
|---|---|---|
| Data preparation | `Scenarios/process_events.py` | Extract 72 h rainfall windows from the Open-Meteo Excel file and build the event folders |
| Data preparation | `DRL-control/prepare_full_rainfall_data.py` | Pad each `*_SWMM.npy` with `PRE_HOURS` zeros before and `POST_HOURS` zeros after, producing `*_FULL_SWMM.npy` |
| Step 1 | `DRL-control/step1-BC-control/main_BCtest.py` | Closed-loop BC simulation; writes `results/bc_results_<event>.npy` |
| Step 2 | `DRL-control/step2-MPC-control-best/main_MPCtest.py` | Closed-loop MPC + PSO; writes `results/mpc_results_<event>.npy` |
| Step 3 | `DRL-control/step3-BCAgent-control/main_BCAgenttest.py` | Closed-loop AgenticAI-BC; writes `results/bc_agent_results_<event>.npy` |
| Step 4 | `DRL-control/step4-uncertainty/run_uncertainty.py` | Uncertainty experiments (baseline / synonym / state noise) under `results_uncertainty/` |
| Reporting | `results_*.py` (project root) | Figures, CSV tables, Markdown reports and statistical tests |

### AgenticAI-BC in brief

1. BC computes a base 7-pump action at every 5 min control step.
2. If a warning in `Event_XX_warnings.md` becomes active, or the state deviates enough, the
   LLM performs a full analysis (Mode A) and returns a JSON action correction.
3. Only off → on changes are accepted, so the agent can only relax, never tighten, the rule
   policy.
4. Every step goes through an independent timing-validation call (Mode B, or local rules)
   before the action is applied; otherwise the BC action is used.
5. The LLM strategy is refreshed every 6 steps, or earlier when storage levels change by more
   than 15% or actual rainfall exceeds 150% of the estimated peak.

## Repository layout

```
Agent_UDSRTC/
├── README.md
├── results_*.py                       # 13 result/visualization/report scripts
├── DRL-control/
│   ├── time_config.py                 # Shared time parameters (PRE/POST/step size)
│   ├── prepare_full_rainfall_data.py  # Generate *_FULL_SWMM.npy
│   ├── BC/BC.py                       # Rule controller (BC)
│   ├── SWMM_control/                  # SWMM environment, chaohu.inp, action tables, YAML config
│   ├── step1-BC-control/              # BC baseline
│   ├── step2-MPC-control-best/        # MPC + PSO
│   ├── step3-BCAgent-control/         # AgenticAI-BC (DeepSeek)
│   ├── step3-BCAgent-control-GLM/     # Same code, GLM backend
│   ├── step3-BCAgent-control-Kimi/    # Same code, Kimi backend
│   ├── step3-BCAgent-control-MiniMax/ # Same code, MiniMax backend
│   └── step4-uncertainty/             # Uncertainty runners, synonym/state-noise generators
├── Scenarios/
│   ├── NMC_Events_2015_2025/          # 10 event folders (Event_01 ... Event_10)
│   ├── Chaohu_Rainfall_2015-2025_OpenMeteo.xlsx
│   ├── 中央气象台_巢湖降雨预警_2015_2025.md
│   ├── Prompt_*.md                    # Data-collection / prompt documentation
│   ├── process_events.py              # Build event folders from the Excel file
│   └── fix_event_rainfall.py          # Fix rainfall/time-axis offsets for Event_01/02
└── Results/
    ├── FigControlperformance/          # F+C curve figures
    ├── FigPerformanceAction/           # Pump-action figures
    ├── FigRainEvent/                   # Rainfall event figures
    ├── LLMInteractionJSON/             # Per-event LLM trace reports
    ├── LLMUsage/                       # Token usage, cost, hypothesis tests
    ├── Reasoning/                      # Per-backend reasoning reports
    └── table_FC_*.csv                  # Summary metric tables
```

Each event folder contains:

```
Event_XX_.../
├── README.md                 # Event metadata; contains the "data window" used to align time
├── Event_XX_warnings.md      # Warning records parsed by the agent
├── Event_XX_warnings_EN.md   # English copy of the warning records
├── *_rainfall.csv            # Rainfall series
├── *_SWMM.npy                # shape (N, 2): [elapsed_hours, mm/hr]
└── *_FULL_SWMM.npy           # PRE zeros + rainfall + POST zeros
```

## Requirements

- Python 3.12 (Windows is assumed: the SWMM DLL is loaded through `pyswmm`)
- A working SWMM installation / DLL visible to `pyswmm`
- Python packages:

```bash
pip install numpy pandas matplotlib scipy pyswmm swmm_api PyYAML joblib openai requests openpyxl
# optional, only for the Nemenyi post-hoc test
pip install scikit-posthocs
```

On conda/Windows, `SWMM_ENV_control.py` sets `CONDA_DLL_SEARCH_MODIFICATION_ENABLE=1` so that
`pyswmm` can locate the SWMM DLL. Keep this in mind if you run the scripts in a different
environment.

## Quick start

All paths below are relative to the project root.

```bash
# 1. Build the padded rainfall arrays (run once)
cd DRL-control
python prepare_full_rainfall_data.py

# 2. Run the controllers
python step1-BC-control/main_BCtest.py
python step2-MPC-control-best/main_MPCtest.py
python step3-BCAgent-control/main_BCAgenttest.py

# 3. Run the uncertainty experiments
python step4-uncertainty/run_uncertainty.py --experiment all --skip-existing
# or individually
python step4-uncertainty/run_synonym.py --skip-existing
python step4-uncertainty/run_state_noise.py --skip-existing

# 4. Produce figures and tables
cd ..
python results_FC.py
python results_FC_full.py
python results_llm_usage_synonym.py
```

`main_BCtest.py`, `main_MPCtest.py` and `main_BCAgenttest.py` do **not** use `argparse`;
their configuration is defined by constants at the top of each file (for example
`ENABLE_LLM_ADJUSTMENT`, `PREDICTION_HORIZON`, `PSO_POPULATION`, `TEST_MODE`,
`START_EVENT_INDEX`). Only the step 4 runners expose command-line options:

```bash
python step4-uncertainty/run_uncertainty.py --experiment {all,baseline,synonym,state_noise} \
    --backend {DeepSeek,GLM,Kimi,MiniMax} --skip-existing
```

## Result scripts

| Script | Main output |
|---|---|
| `results_FC.py` | `Results/FigControlperformance/FC_curve_vs_rainfall.png`, `Results/table_FC_NMC.csv` |
| `results_FC_full.py` | `FC_curve_vs_rainfall_full.png`, `Results/table_FC_NMC_full.csv` |
| `results_FC_perfectMPCPPO.py` | `FC_curve_vs_rainfall_perfectcompare.png`, `table_FC_NMC_perfectcompare.csv` |
| `results_varLLM.py` | `varLLM_FC_curve_vs_rainfall.png`, `Results/table_FC_varLLM.csv` |
| `results_Action_total.py` | `Results/FigPerformanceAction/FigAction/FigAction.png` |
| `results_FC_Action_per_event.py` | `Results/FigPerformanceAction/FC_Action_E4-10.png` |
| `results_FC_Action_per_event_S11.py` | `Results/FigPerformanceAction/FC_E1-10.png`, `Action_E1-10.png` |
| `results_FCfull_Actiontotal.py` | `Results/FigPerformanceAction/FCfull_Actiontotal.png` |
| `results_rainfall_event.py` | `Results/FigRainEvent/rainfall_timeseries_events.png` |
| `results_json.py` | `Results/LLMInteractionJSON/Event_XX_*.md` |
| `results_reasoning.py` | `Results/Reasoning/reasoning_<backend>.md` |
| `results_llm_usage_synonym.py` | `Results/LLMUsage/llm_usage_summary.csv`, hypothesis-test report, CD diagram |
| `results_synonym_boxplot.py` | `Results/LLMUsage/FigUncertainty/synonym_cov_bar.png` |

## Configuration

### Time parameters

`DRL-control/time_config.py`:

- `PRE_HOURS = 6`, `POST_HOURS = 18`
- `RAIN_START_HOUR = 8`
- `INTERVAL_MIN = 5` (12 control steps per hour)
- `compute_sim_start_from_readme()` parses the real data-window start from each event README

### LLM backends

The four AgenticAI-BC variants share the same code and differ only in their LLM
configuration (model / base URL / API key):

| Backend | Base URL | Model |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-v4-flash` (reasoning enabled) |
| GLM (Zhipu) | `https://open.bigmodel.cn/api/paas/v4/` | `glm-4-flash` |
| Kimi (Moonshot) | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| MiniMax | `https://api.minimaxi.com/v1` | `MiniMax-M3` |

Configuration lives in `DRL-control/step4-uncertainty/config_uncertainty.py` and in the
`LLM configuration` block of each `main_BCAgenttest.py`.

> **Security note.** API keys are currently hardcoded in the source files. Before publishing
> or sharing this repository, move them to environment variables (for example
> `os.environ["DEEPSEEK_API_KEY"]`) and rotate every exposed key. Do not commit real keys.

## Metrics

- **F** – flooding volume (m³)
- **C** – combined sewer overflow volume (m³)
- **F+C** – the objective minimized by the controllers
- **Improvement** – relative reduction of F+C compared with the BC baseline

The summary tables use columns such as `BC_F+C`, `MPC_F+C`, `BCAg_F+C`,
`MPCvBC_Improve` and `BCAgvBC_Improve` (see `Results/table_FC_NMC.csv`).

## Uncertainty experiments

`DRL-control/step4-uncertainty/` implements three experiment families:

- `baseline` – reuse the original step 3 results without any LLM call.
- `synonym` – replace synonyms in the warning text to test language robustness.
- `state_noise` – add 5% relative Gaussian noise to observed depths/flows to test sensing
  robustness.

`analyze_uncertainty_results.py` aggregates mean, standard deviation and coefficient of
variation, and produces comparison figures.

## Important notes

- This snapshot contains the control and evaluation code. PPO training code and
  `step2-DRL-control*` / `step3-Agent-control` directories referenced by some result scripts
  are not included; those curves are skipped when the data is missing.
- `Scenarios/process_events.py` and `Scenarios/fix_event_rainfall.py` contain hardcoded
  absolute Windows paths. Update them to your local project path before running.
- The SWMM DLL cannot load non-ASCII paths, so temporary INP files are named by index and
  written to ASCII-only directories.
- All code comments and docstrings are in English. Chinese text inside data strings is
  intentional: these are LLM prompts, event/warning names, plot labels and report templates
  that belong to the experiment data and must not be translated.
- Each event must close its SWMM `Simulation` explicitly; otherwise the next run may raise
  `MultiSimulationError` because of leftover DLL state.

