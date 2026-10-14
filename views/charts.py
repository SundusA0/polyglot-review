"""Plotly figures. Kept separate so the pages stay readable."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC"]
QUADRANT_COLORS = {
    "core workflow": "#4C78A8",
    "broad, shallow": "#F58518",
    "niche, deep": "#54A24B",
    "low traction": "#BAB0AC",
}
VERSION_COLORS = {"v1": "#BAB0AC", "v2": "#4C78A8", "v3": "#54A24B"}


def _base(fig: go.Figure, height: int = 380) -> go.Figure:
    # Title sits at the very top, legend in a band between the title and the plot.
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=85, b=10),
        title=dict(y=0.97, yanchor="top", x=0, xanchor="left", font=dict(size=16)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None),
        font=dict(size=13),
    )
    return fig


def reach_depth_scatter(summary: pd.DataFrame) -> go.Figure:
    fig = px.scatter(
        summary,
        x="reach_pct", y="events_per_user", size="events", color="quadrant", text="feature",
        color_discrete_map=QUADRANT_COLORS, size_max=48,
        labels={"reach_pct": "Reach (% of active users)", "events_per_user": "Events per user", "quadrant": ""},
        hover_data={"unique_users": True, "events": True, "accounts": True, "reach_pct": ":.1f",
                    "events_per_user": ":.2f", "feature": False, "quadrant": False},
        title="Reach vs depth by feature",
    )
    fig.update_traces(textposition="top center", marker=dict(opacity=0.85, line=dict(width=1, color="white")))
    if not summary.empty:
        fig.add_vline(x=summary["reach_pct"].median(), line_dash="dot", line_color="gray", opacity=0.5)
        fig.add_hline(y=summary["events_per_user"].median(), line_dash="dot", line_color="gray", opacity=0.5)
    fig.update_xaxes(rangemode="tozero")
    fig.update_yaxes(rangemode="tozero")
    return _base(fig, 440)


def weekly_lines(trend: pd.DataFrame, metric: str = "unique_users", title: str = "Weekly unique users") -> go.Figure:
    fig = px.line(
        trend, x="week", y=metric, color="feature", markers=True,
        color_discrete_sequence=PALETTE,
        labels={"week": "Week starting", metric: metric.replace("_", " ").title(), "feature": ""},
        title=title,
    )
    fig.update_yaxes(rangemode="tozero")
    return _base(fig, 400)


def locale_bar(locale_df: pd.DataFrame, title: str = "Events by locale") -> go.Figure:
    df = locale_df.sort_values("events", ascending=True)
    fig = px.bar(
        df, x="events", y="language", orientation="h", text="share_pct",
        color_discrete_sequence=["#4C78A8"],
        labels={"events": "Events", "language": ""},
        hover_data={"unique_users": True, "share_pct": ":.1f"},
        title=title,
    )
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside", cliponaxis=False)
    return _base(fig, 360)


def reconciliation_bar(recon_summary: pd.DataFrame) -> go.Figure:
    df = recon_summary.sort_values("events_delta_pct")
    colors = ["#E45756" if abs(v) > 5 else "#4C78A8" for v in df["events_delta_pct"].fillna(0)]
    fig = go.Figure(go.Bar(
        x=df["events_delta_pct"], y=df["feature"], orientation="h", marker_color=colors,
        text=[f"{v:+.1f}%" for v in df["events_delta_pct"].fillna(0)], textposition="outside",
        hovertemplate="%{y}<br>Pendo vs warehouse (web): %{x:+.1f}%<extra></extra>",
    ))
    fig.add_vline(x=0, line_color="gray", opacity=0.6)
    fig.update_layout(title="Pendo web events vs warehouse web events (delta %)",
                      xaxis_title="Delta (%)", yaxis_title="")
    return _base(fig, 360)


def version_metric_bars(agg: pd.DataFrame, metric: str, title: str) -> go.Figure:
    fig = px.bar(
        agg, x="language_name", y=metric, color="prompt_version", barmode="group",
        color_discrete_map=VERSION_COLORS, color_discrete_sequence=PALETTE,
        labels={"language_name": "", metric: "Mean score (0-100)", "prompt_version": ""},
        title=title, text=metric,
    )
    fig.update_traces(texttemplate="%{text:.0f}", textposition="outside", cliponaxis=False)
    fig.update_yaxes(range=[0, 108])
    return _base(fig, 380)


def tag_frequency_bars(tag_counts: pd.DataFrame) -> go.Figure:
    """tag_counts columns: prompt_version, tag, count."""
    fig = px.bar(
        tag_counts, x="tag", y="count", color="prompt_version", barmode="group",
        color_discrete_map=VERSION_COLORS, color_discrete_sequence=PALETTE,
        labels={"tag": "", "count": "Responses flagged", "prompt_version": ""},
        title="Suggested error tags by prompt version",
    )
    return _base(fig, 380)


def calibration_bars(cal: pd.DataFrame) -> go.Figure:
    df = cal.melt(id_vars=["tag"], value_vars=["recall", "precision"], var_name="metric", value_name="value")
    fig = px.bar(
        df, x="tag", y="value", color="metric", barmode="group",
        color_discrete_sequence=["#4C78A8", "#54A24B"],
        labels={"tag": "", "value": "", "metric": ""},
        title="Auto-tag recall and precision against injected errors",
        text="value",
    )
    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside", cliponaxis=False)
    fig.update_yaxes(range=[0, 1.12])
    fig.update_xaxes(tickangle=-25)
    return _base(fig, 400)
