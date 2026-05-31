INTENT_TRIP_PLANNER = {
    "user_message": (
        "compose meta-skill for trip planning: weather + POIs in parallel, then itinerary"
    ),
    "expected_pattern": "p2_fan_out_merge",
    "co_occurrence_seed": [["weather", "multi-search-engine", "summarize"]] * 3,
}
