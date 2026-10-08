## Template candidate(s) from this week's Imgflip scan

Found by `backend/scripts/trend_pipeline.py`. Nothing here is in the catalog until this pull request is merged. This file is an example of the description the workflow writes. A real run overwrites it and uses it as the pull request's description.

### `example_template` — Example Template

Source: [Example Template on Imgflip](https://imgflip.com/meme/000000)

Closest existing match: `some_existing_template` (similarity 0.612, below the 0.95 duplicate threshold)

**`USE_WHEN`:**
```python
"example_template": "EXAMPLE LABEL: one dense sentence. NOT for X (use Y).",
```

**Box layout note:** Standard top/bottom layout. (falls back to the generic top/bottom `DEFAULT_BOXES` layout unless someone later adds a custom `TextBoxConfig` for it in `image_processing/template_configs.py`)
