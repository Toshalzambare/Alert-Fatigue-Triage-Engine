# 1. GENERATE — Bulk load all 478 events (narratives + traps + noise)
python db/generate_mock_data.py

# 2. VIEW — Inspect what's in the database
python db/view_db.py                                        # full overview
python db/view_db.py --scenario bruteforce_then_success     # filter by scenario
python db/view_db.py --user j.smith                         # filter by user
python db/view_db.py --samples 10                           # show 10 sample docs

# 3. STREAM — Push new live events at intervals (Ctrl+C to stop)
python db/realtime_log_streamer.py                          # default: every 5s
python db/realtime_log_streamer.py --interval 2             # every 2 seconds

# 4. CLEAR — Wipe the database clean (prompts y/n)
python db/clear_db.py
