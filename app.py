from __future__ import annotations

from pathlib import Path
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


DATA_DIR = Path("labelled_data")
FILEPATH_TS_PATTERN = re.compile(r"(?P<date>\d{8})_(?P<time>\d{6})")
LABEL_ORDER = ["GHOST-aurora", "non-GHOST-aurora", "Unknown"]
LABEL_COLORS = {
    "GHOST-aurora": "#1f77b4",
    "non-GHOST-aurora": "#d62728",
    "Unknown": "#7f7f7f",
}


@st.cache_data(show_spinner=False)
def load_labelled_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    csv_paths = sorted(data_dir.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    frames = []
    for csv_path in csv_paths:
        frame = pd.read_csv(csv_path)
        frame["source_csv"] = csv_path.name
        frames.append(frame)

    raw_df = pd.concat(frames, ignore_index=True)
    if not {"filepath", "label"}.issubset(raw_df.columns):
        raise ValueError("Each CSV must contain 'filepath' and 'label' columns.")

    work = raw_df[["filepath", "label", "source_csv"]].copy()
    work["label"] = work["label"].astype(str).str.strip()

    extracted = work["filepath"].astype(str).str.extract(FILEPATH_TS_PATTERN)
    work["date_token"] = extracted["date"]
    work["time_token"] = extracted["time"]
    work["datetime_ut"] = pd.to_datetime(
        work["date_token"] + work["time_token"],
        format="%Y%m%d%H%M%S",
        errors="coerce",
        utc=True,
    )

    invalid_mask = (
        work["date_token"].isna()
        | work["time_token"].isna()
        | work["datetime_ut"].isna()
    )
    invalid_rows = work.loc[invalid_mask, ["filepath", "label", "source_csv"]].copy()
    parsed = work.loc[~invalid_mask].copy()

    parsed["date_ut"] = parsed["datetime_ut"].dt.strftime("%Y-%m-%d")
    parsed["time_ut"] = parsed["datetime_ut"].dt.strftime("%H:%M:%S")
    parsed["hour_ut"] = parsed["datetime_ut"].dt.hour
    parsed["minute_of_day"] = (
        parsed["datetime_ut"].dt.hour * 60 + parsed["datetime_ut"].dt.minute
    )
    parsed["second_of_day"] = parsed["minute_of_day"] * 60 + parsed["datetime_ut"].dt.second
    parsed["label"] = pd.Categorical(parsed["label"], categories=LABEL_ORDER, ordered=True)

    return parsed, invalid_rows, [p.name for p in csv_paths]


def with_bins(dataframe: pd.DataFrame, bin_minutes: int) -> pd.DataFrame:
    binned = dataframe.copy()
    binned["bin_minute"] = (binned["minute_of_day"] // bin_minutes) * bin_minutes
    binned["bin_label"] = (
        (binned["bin_minute"] // 60).astype(str).str.zfill(2)
        + ":"
        + (binned["bin_minute"] % 60).astype(str).str.zfill(2)
    )
    return binned


def aggregate_profile(dataframe: pd.DataFrame, bin_minutes: int) -> pd.DataFrame:
    bins = list(range(0, 1440, bin_minutes))
    idx = pd.MultiIndex.from_product([bins, LABEL_ORDER], names=["bin_minute", "label"])
    grouped = dataframe.groupby(["bin_minute", "label"], observed=False).size().rename("count")
    full = grouped.reindex(idx, fill_value=0).reset_index()
    full["bin_label"] = (
        (full["bin_minute"] // 60).astype(str).str.zfill(2)
        + ":"
        + (full["bin_minute"] % 60).astype(str).str.zfill(2)
    )
    return full


def build_probability_frame(profile_df: pd.DataFrame, smoothing_bins: int) -> pd.DataFrame:
    pivot = profile_df.pivot(index="bin_minute", columns="label", values="count").fillna(0)
    for label in LABEL_ORDER:
        if label not in pivot.columns:
            pivot[label] = 0

    known = pivot["GHOST-aurora"] + pivot["non-GHOST-aurora"]
    total = known + pivot["Unknown"]
    # Use NaN denominators for empty bins to avoid NAType -> float cast errors.
    prob = pivot["GHOST-aurora"] / known.replace(0, float("nan"))
    unknown_fraction = pivot["Unknown"] / total.replace(0, float("nan"))

    out = pd.DataFrame(
        {
            "bin_minute": pivot.index,
            "p_ghost_given_known": prob,
            "unknown_fraction": unknown_fraction,
        }
    ).reset_index(drop=True)
    out = out.sort_values("bin_minute")
    out["bin_label"] = (
        (out["bin_minute"] // 60).astype(str).str.zfill(2)
        + ":"
        + (out["bin_minute"] % 60).astype(str).str.zfill(2)
    )

    if smoothing_bins > 1:
        out["p_ghost_given_known"] = (
            out["p_ghost_given_known"]
            .rolling(window=smoothing_bins, min_periods=1, center=True)
            .mean()
        )
        out["unknown_fraction"] = (
            out["unknown_fraction"]
            .rolling(window=smoothing_bins, min_periods=1, center=True)
            .mean()
        )
    return out


def build_hour_heatmap(dataframe: pd.DataFrame) -> pd.DataFrame:
    idx = pd.MultiIndex.from_product([range(24), LABEL_ORDER], names=["hour_ut", "label"])
    grouped = dataframe.groupby(["hour_ut", "label"], observed=False).size().rename("count")
    return grouped.reindex(idx, fill_value=0).reset_index()


def main() -> None:
    st.set_page_config(page_title="GHOST Time-of-Day Dashboard", layout="wide")
    st.title("GHOST Time-of-Day Dashboard")
    st.caption("Visualise when GHOST-aurora, non-GHOST-aurora, and Unknown occur in UT.")

    try:
        parsed_df, invalid_rows, csv_names = load_labelled_data(DATA_DIR)
    except (FileNotFoundError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    if parsed_df.empty:
        st.error("No valid rows after parsing filepath timestamps.")
        st.stop()

    st.sidebar.header("Controls")
    all_dates = sorted(parsed_df["date_ut"].unique())
    selected_dates = st.sidebar.multiselect("UT dates", all_dates, default=all_dates)
    bin_minutes = st.sidebar.selectbox("Bin size (minutes)", options=[5, 10, 15, 30], index=1)
    smoothing_bins = st.sidebar.slider("Smoothing window (bins)", min_value=1, max_value=12, value=1)

    if not selected_dates:
        st.warning("Select at least one UT date to display charts.")
        st.stop()

    filtered = parsed_df.loc[parsed_df["date_ut"].isin(selected_dates)].copy()
    filtered = with_bins(filtered, bin_minutes)

    total_rows = len(filtered)
    ghost_rows = int((filtered["label"] == "GHOST-aurora").sum())
    non_rows = int((filtered["label"] == "non-GHOST-aurora").sum())
    unknown_rows = int((filtered["label"] == "Unknown").sum())
    known_rows = ghost_rows + non_rows
    ghost_rate_known = (ghost_rows / known_rows) if known_rows else 0.0

    st.subheader("Overview")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total images", f"{total_rows:,}")
    m2.metric("GHOST-aurora", f"{ghost_rows:,}")
    m3.metric("non-GHOST-aurora", f"{non_rows:,}")
    m4.metric("Unknown", f"{unknown_rows:,}")
    m5.metric("P(GHOST | known)", f"{ghost_rate_known:.1%}")

    st.caption(
        f"Loaded {len(csv_names)} CSV file(s): {', '.join(csv_names)}. "
        f"Selected date coverage: {', '.join(selected_dates)}"
    )

    profile = aggregate_profile(filtered, bin_minutes)
    fig_profile = px.area(
        profile,
        x="bin_minute",
        y="count",
        color="label",
        category_orders={"label": LABEL_ORDER},
        color_discrete_map=LABEL_COLORS,
        labels={"bin_minute": "Time of day (UT)", "count": "Image count", "label": "Label"},
        title=f"Time-of-Day Label Profile ({bin_minutes}-minute bins)",
    )
    fig_profile.update_xaxes(
        tickvals=list(range(0, 1441, 60)),
        ticktext=[f"{hour:02d}:00" for hour in range(25)],
        range=[0, 1439],
    )
    st.plotly_chart(fig_profile, use_container_width=True)

    prob_df = build_probability_frame(profile, smoothing_bins)
    fig_prob = go.Figure()
    fig_prob.add_trace(
        go.Scatter(
            x=prob_df["bin_minute"],
            y=prob_df["p_ghost_given_known"],
            mode="lines",
            name="P(GHOST | known)",
            line={"color": LABEL_COLORS["GHOST-aurora"], "width": 2},
        )
    )
    fig_prob.add_trace(
        go.Scatter(
            x=prob_df["bin_minute"],
            y=prob_df["unknown_fraction"],
            mode="lines",
            name="Unknown fraction",
            line={"color": LABEL_COLORS["Unknown"], "width": 2, "dash": "dot"},
        )
    )
    fig_prob.update_layout(
        title="Probability View by Time of Day",
        xaxis_title="Time of day (UT)",
        yaxis_title="Fraction",
        yaxis_range=[0, 1],
        legend_title_text="Metric",
    )
    fig_prob.update_xaxes(
        tickvals=list(range(0, 1441, 60)),
        ticktext=[f"{hour:02d}:00" for hour in range(25)],
        range=[0, 1439],
    )
    st.plotly_chart(fig_prob, use_container_width=True)

    heatmap_data = build_hour_heatmap(filtered)
    pivot = (
        heatmap_data.pivot(index="label", columns="hour_ut", values="count")
        .reindex(LABEL_ORDER)
        .fillna(0)
    )
    fig_heatmap = px.imshow(
        pivot,
        aspect="auto",
        labels={"x": "Hour (UT)", "y": "Label", "color": "Count"},
        title="Hourly Label Heatmap",
        text_auto=True,
        color_continuous_scale="Viridis",
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)

    sequence_df = filtered.sort_values("datetime_ut")
    fig_sequence = px.scatter(
        sequence_df,
        x="datetime_ut",
        y="label",
        color="label",
        category_orders={"label": LABEL_ORDER},
        color_discrete_map=LABEL_COLORS,
        labels={"datetime_ut": "Datetime (UT)", "label": "Label"},
        title="Sequence Strip (Event Continuity)",
        opacity=0.8,
    )
    fig_sequence.update_traces(marker={"size": 5})
    st.plotly_chart(fig_sequence, use_container_width=True)

    with st.expander("Parsing and data quality details"):
        st.write(f"Valid rows used: {len(parsed_df):,}")
        st.write(f"Rows skipped due to unparsable filepath timestamp: {len(invalid_rows):,}")
        if not invalid_rows.empty:
            st.dataframe(invalid_rows.head(20), use_container_width=True)


if __name__ == "__main__":
    main()
