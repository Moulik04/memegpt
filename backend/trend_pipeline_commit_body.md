## New template(s) added by this week's Imgflip scan

Automated by `backend/scripts/trend_pipeline.py`. Each one cleared the perceptual-hash duplicate filter, the same content-moderation gate every user-uploaded image goes through, and the workflow's own pytest run before landing here — no PR, no manual merge.

### `example_template` — Example Template

Source: [Example Template on Imgflip](https://imgflip.com/meme/000000)

Closest existing match: `some_existing_template` (similarity 0.612, below the 0.95 duplicate threshold)

**`USE_WHEN`:**
```python
"example_template": "EXAMPLE LABEL: one dense sentence. NOT for X (use Y).",
```

**Box layout note:** Standard top/bottom layout. (falls back to the generic top/bottom `DEFAULT_BOXES` layout unless someone later adds a custom `TextBoxConfig` for it in `image_processing/template_configs.py`)
