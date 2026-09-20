"""Frozen combat scenario shared by maintained tools and acceptance checks."""

DECK = [
    *(
        {"instance_id": f"strike-{index}", "model_id": "STRIKE_IRONCLAD"}
        for index in range(5)
    ),
    *(
        {"instance_id": f"defend-{index}", "model_id": "DEFEND_IRONCLAD"}
        for index in range(5)
    ),
]

SCENARIO = {
    "game_build": {},
    "seed": "NATIVESIMSPIKE",
    "rng_counters": {},
    "character": "IRONCLAD",
    "ascension": 0,
    "encounter": "first",
    "current_hp": 80,
    "max_hp": 80,
    "gold": 99,
    "deck": DECK,
    "initial_hand": ["strike-0"],
    "relics": [],
    "potions": [],
}
