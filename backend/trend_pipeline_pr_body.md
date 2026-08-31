## New template candidate(s) from this week's Imgflip scan

Automated by `backend/scripts/trend_pipeline.py`. **Nothing here is merged automatically** — review every candidate below before approving.

### Review checklist

- [ ] For each candidate: confirm it's not a duplicate of an existing template under a different name (see "closest existing match" per candidate)
- [ ] Read the drafted `USE_WHEN` — does the wording actually match the image, and are the "NOT for X" cross-references correct?
- [ ] Check against this catalog's known confusion clusters:
- drake / evil_kermit / two_buttons
- distracted_boyfriend / left_exit_12 / uno_draw_25_cards
- leonardo_dicaprio_cheers / laughing_leo
- spiderman_pointing_at_spiderman / spider_man_triple
- megamind_no_bitches / megamind_peeking
- is_this_a_pigeon / theyre_the_same_picture
- bell_curve / midwit_bell_curve
- [ ] Check the box layout note — if it suggests a multi-panel or non-default layout, add a custom `TextBoxConfig` in `image_processing/template_configs.py` before merging (not done automatically)
- [ ] Generate a real test meme locally to confirm captions render legibly

---

### `c_mon_do_something` — c'mon do something

Source: [c'mon do something on Imgflip](https://imgflip.com/meme/20007896)

Closest existing match: `marked_safe_from` (similarity 0.789, below the 0.95 duplicate threshold)

**Drafted `USE_WHEN`:**
```python
"c_mon_do_something": "SILENT WITNESS: A crude, masked figure stands off to the side, pointing an accusatory finger at a specific action or event while maintaining total anonymity and deadpan silence. NOT for two people arguing (woman_yelling_at_cat) and NOT for a generic shocked reaction (surprised_pikachu).",
```

**Box layout note:** Requires a single caption box placed in the empty space where the figure is pointing.

