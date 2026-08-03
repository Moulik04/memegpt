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

### `bernie_i_am_once_again_asking_for_your_support` — Bernie I Am Once Again Asking For Your Support

Source: [Bernie I Am Once Again Asking For Your Support on Imgflip](https://imgflip.com/meme/222403160)

Closest existing match: `bernie_sanders_once_again_asking` (similarity 0.672, below the 0.95 duplicate threshold)

**Drafted `USE_WHEN`:**
```python
"bernie_i_am_once_again_asking_for_your_support": "UNYIELDING DEMAND: A serious, repetitive plea or question that is being ignored or dismissed, emphasizing the persistence of the speaker despite the lack of response. NOT for a sudden realization of consequences (surprised_pikachu) or a smug rejection of an option (drake).",
```

**Box layout note:** Single panel with text overlaid on the subject's torso.
### `grim_reaper_knocking_door` — Grim Reaper Knocking Door

Source: [Grim Reaper Knocking Door on Imgflip](https://imgflip.com/meme/104893621)

Closest existing match: `drake` (similarity 0.609, below the 0.95 duplicate threshold)

**Drafted `USE_WHEN`:**
```python
"grim_reaper_knocking_door": "DRAFT FAILED \u2014 write this entry by hand before merging.",
```

**Box layout note:** (drafting failed: Client error '429 Too Many Requests' for url 'https://api.groq.com/openai/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429)
### `c_mon_do_something` — c'mon do something

Source: [c'mon do something on Imgflip](https://imgflip.com/meme/20007896)

Closest existing match: `marked_safe_from` (similarity 0.789, below the 0.95 duplicate threshold)

**Drafted `USE_WHEN`:**
```python
"c_mon_do_something": "DRAFT FAILED \u2014 write this entry by hand before merging.",
```

**Box layout note:** (drafting failed: Client error '429 Too Many Requests' for url 'https://api.groq.com/openai/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429)

