"""
Upload safety gate — ALL uploaded media enters through safe_ingest.safe_ingest().
Never bypass it: no other code path may hand raw upload bytes to a model,
disk, or renderer.
"""
