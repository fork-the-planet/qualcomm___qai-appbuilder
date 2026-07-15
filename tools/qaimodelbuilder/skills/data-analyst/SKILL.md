---
name: Data Analyst
description: Analyze data, generate statistics, create visualizations, and extract insights from datasets.
tags: data, analysis, statistics, csv
use_for: Analyzing CSV/JSON data, computing statistics, finding patterns, generating reports
---

# Data Analyst Skill

Analyze data files and generate insights using `read`, `exec`, and `write` tools.

## When to Use

- Analyzing CSV, JSON, or Excel files
- Computing statistics (mean, median, std dev, etc.)
- Finding patterns and anomalies
- Generating summary reports
- Data cleaning and transformation

## Workflow

1. `read(data_file)` – Load the data
2. `exec("python -c '...'")` – Run analysis scripts
3. `write(report_file)` – Save results

## Example Analysis Script

```python
import json, statistics

data = json.load(open("data.json"))
values = [row["value"] for row in data]
print(f"Count: {len(values)}")
print(f"Mean: {statistics.mean(values):.2f}")
print(f"Median: {statistics.median(values):.2f}")
print(f"Std Dev: {statistics.stdev(values):.2f}")
```
