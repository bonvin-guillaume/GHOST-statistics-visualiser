# GHOST Time-of-Day Dashboard

This project provides a Streamlit dashboard to visualise when `GHOST-aurora`, `non-GHOST-aurora`, and `Unknown` labels occur during the UT day.

The dashboard reads all CSV files in `labelled_data/` with schema:

- `filepath` (image filepath containing timestamp like `.../LYR-Sony-YYYYMMDD_HHMMSS.jpg`)
- `label` (`GHOST-aurora`, `non-GHOST-aurora`, or `Unknown`)

## Setup

1. Create and activate a virtual environment (recommended):
   - macOS/Linux:
     - `python3 -m venv .venv`
     - `source .venv/bin/activate`
2. Install dependencies:
   - `pip install -r requirements.txt`

## Run

From the project root:

- `streamlit run app.py`

Streamlit will print a local URL (usually `http://localhost:8501`) to open in your browser.

## Dashboard Views

- **Overview KPIs**
  - Total images, per-label counts, and `P(GHOST | known)` where known = `GHOST-aurora + non-GHOST-aurora`.

- **Time-of-Day Label Profile**
  - Stacked area chart by time-of-day bins showing how each label is distributed through 24h UT.

- **Probability View**
  - `P(GHOST | known)` versus time of day.
  - `Unknown fraction` versus time of day.
  - Optional smoothing (in bins) can reduce short-scale noise.

- **Hourly Label Heatmap**
  - Counts by hour (`0..23` UT) and label.

- **Sequence Strip**
  - Point timeline in chronological order to reveal contiguous runs and transitions between labels.

- **Parsing/Data Quality Panel**
  - Reports rows skipped due to unparseable filepath timestamps.
  - Shows sample invalid rows when present.

## Controls

- **UT dates**: filter one or multiple dates (works with one or many CSV files).
- **Bin size**: choose 5, 10, 15, or 30-minute aggregation.
- **Smoothing window**: rolling average width in number of bins for the probability view.

## Notes

- Timestamps are extracted directly from filepath tokens matching `YYYYMMDD_HHMMSS`.
- Datetimes are parsed as UTC (`UT`).
- The app is structured to support multiple CSV files/dates without redesign.
# GHOST-statistics-visualiser
