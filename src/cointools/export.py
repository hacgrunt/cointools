"""Generate a self-contained HTML report with visualizations.

Uses Chart.js via CDN — the output is a single .html file that can be
opened in any browser or dropped on any free static host.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from cointools.tracker import AnalysisReport, HolderAnalysis, Sentiment, Signal

_SIGNAL_COLORS = {
    Signal.BUY: "#22c55e",
    Signal.SELL: "#ef4444",
    Signal.HOLD: "#6b7280",
    Signal.NEW: "#3b82f6",
    Signal.UNKNOWN: "#eab308",
}

_SIGNAL_LABELS = {
    Signal.BUY: "BUY",
    Signal.SELL: "SELL",
    Signal.HOLD: "HOLD",
    Signal.NEW: "NEW",
    Signal.UNKNOWN: "???",
}

_SENTIMENT_COLORS = {
    Sentiment.ACCUMULATION: "#22c55e",
    Sentiment.DISTRIBUTION: "#ef4444",
    Sentiment.NEUTRAL: "#eab308",
}


def _shorten(addr: str | None, n: int = 6) -> str:
    if not addr:
        return "—"
    if len(addr) <= n * 2 + 2:
        return addr
    return f"{addr[:n]}..{addr[-n:]}"


def _fmt_balance(val: float | None) -> str:
    if val is None:
        return "—"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:,.2f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:,.2f}M"
    if val >= 1_000:
        return f"{val:,.0f}"
    return f"{val:,.2f}"


def _build_chart_data(report: AnalysisReport) -> dict:
    labels = []
    current_vals = []
    change_vals = []
    colors = []

    for h in report.holders:
        labels.append(_shorten(h.owner_address or h.holder_address, 4))
        current_vals.append(h.current_balance)
        change_vals.append(h.change if h.change is not None else 0)
        colors.append(_SIGNAL_COLORS[h.signal])

    return {
        "labels": labels,
        "current": current_vals,
        "changes": change_vals,
        "colors": colors,
    }


def _build_sentiment_data(report: AnalysisReport) -> dict:
    return {
        "labels": ["Buying", "Selling", "Holding", "New/Unknown"],
        "values": [report.buying, report.selling, report.holding, report.unknown],
        "colors": ["#22c55e", "#ef4444", "#6b7280", "#3b82f6"],
    }


def generate_html_report(report: AnalysisReport, output_path: str) -> None:
    chart_data = _build_chart_data(report)
    sentiment_data = _build_sentiment_data(report)

    sentiment_label = report.sentiment.value
    sentiment_color = _SENTIMENT_COLORS[report.sentiment]

    addr_short = _shorten(report.mint, 8)

    # Build table rows
    rows_html = ""
    for h in report.holders:
        change_str = ""
        if h.change is not None:
            prefix = "+" if h.change > 0 else ""
            pct = f" ({prefix}{h.change_pct:.1f}%)" if h.change_pct is not None else ""
            change_str = f"{prefix}{_fmt_balance(abs(h.change))}{pct}"
        else:
            change_str = "—"

        signal_label = _SIGNAL_LABELS[h.signal]
        signal_color = _SIGNAL_COLORS[h.signal]

        rows_html += f"""
        <tr>
            <td>{h.rank}</td>
            <td class="addr">{html.escape(_shorten(h.owner_address or h.holder_address))}</td>
            <td class="num">{_fmt_balance(h.current_balance)}</td>
            <td class="num" style="color:{signal_color}">{change_str}</td>
            <td><span class="signal" style="background:{signal_color}">{signal_label}</span></td>
        </tr>"""

    template = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cointools Report — {html.escape(addr_short)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #0a0a0a; color: #e5e5e5; padding: 2rem; max-width: 1000px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.3rem; }}
  .meta {{ color: #737373; margin-bottom: 1.5rem; font-size: 0.85rem; }}
  .sentiment {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px;
                font-weight: 700; font-size: 0.85rem; }}
  .charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
  .chart-box {{ background: #171717; border-radius: 8px; padding: 1rem; }}
  .chart-box h2 {{ font-size: 0.9rem; color: #a3a3a3; margin-bottom: 0.5rem; }}
  canvas {{ max-height: 300px; }}
  table {{ width: 100%; border-collapse: collapse; background: #171717; border-radius: 8px;
           overflow: hidden; }}
  th {{ text-align: left; padding: 0.6rem 0.8rem; background: #262626; color: #a3a3a3;
        font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 0.5rem 0.8rem; border-top: 1px solid #262626; font-size: 0.85rem; }}
  .addr {{ font-family: monospace; color: #a3a3a3; }}
  .num {{ text-align: right; font-family: monospace; }}
  .signal {{ padding: 0.15rem 0.5rem; border-radius: 3px; color: #fff; font-size: 0.75rem;
             font-weight: 600; }}
  .footer {{ margin-top: 1.5rem; color: #525252; font-size: 0.75rem; text-align: center; }}
  @media (max-width: 700px) {{ .charts {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<h1>{html.escape(addr_short)}</h1>
<div class="meta">
  Top holder analysis &middot; {html.escape(report.period)} period &middot;
  <span class="sentiment" style="background:{sentiment_color}">{sentiment_label}</span>
</div>

<div class="charts">
  <div class="chart-box">
    <h2>Balance Changes by Holder</h2>
    <canvas id="changeChart"></canvas>
  </div>
  <div class="chart-box">
    <h2>Holder Sentiment</h2>
    <canvas id="sentimentChart"></canvas>
  </div>
</div>

<table>
  <thead>
    <tr><th>Rank</th><th>Holder</th><th style="text-align:right">Balance</th><th style="text-align:right">Change</th><th>Signal</th></tr>
  </thead>
  <tbody>{rows_html}
  </tbody>
</table>

<div class="footer">Generated by cointools</div>

<script>
const chartData = {json.dumps(chart_data)};
const sentData = {json.dumps(sentiment_data)};

new Chart(document.getElementById('changeChart'), {{
  type: 'bar',
  data: {{
    labels: chartData.labels,
    datasets: [{{
      label: 'Balance Change',
      data: chartData.changes,
      backgroundColor: chartData.colors,
      borderRadius: 3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#737373', font: {{ size: 10 }} }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ color: '#737373' }}, grid: {{ color: '#262626' }} }}
    }}
  }}
}});

const nonZero = sentData.values.filter(v => v > 0);
if (nonZero.length > 0) {{
  new Chart(document.getElementById('sentimentChart'), {{
    type: 'doughnut',
    data: {{
      labels: sentData.labels.filter((_, i) => sentData.values[i] > 0),
      datasets: [{{
        data: sentData.values.filter(v => v > 0),
        backgroundColor: sentData.colors.filter((_, i) => sentData.values[i] > 0),
        borderWidth: 0,
      }}]
    }},
    options: {{
      responsive: true,
      cutout: '60%',
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ color: '#a3a3a3', padding: 12 }} }}
      }}
    }}
  }});
}}
</script>
</body>
</html>"""

    Path(output_path).write_text(template)
