"""Non-sensitive configuration for the only supported allocation method."""

TREE_VERSION = "real-crane-rule-tree-v2"
NODE_ORDER = (
    "input_complete",
    "ladle_state_repair_argon",
    "grade_age_weight_previous_grade",
    "crane_load_time_safety",
    "yellow_rule_score",
)
SCORING_WEIGHTS = {
    "grade": 0.50,
    "age": 0.20,
    "window": 0.15,
    "balance": 0.10,
    "scarcity": 0.05,
}
