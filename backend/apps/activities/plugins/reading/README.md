Scaffolded in M2+ — the "reading" activity-type plugin: schema.py, completion.py, meta.py.
In M1, this activity type is just a plain choices value on Activity.activity_type
(and, where present, a minimal validation schema in apps/activities/registry.py) —
no real plugin framework exists yet. See docs/architecture.md §4 (Activity type plugins),
§9 (Content embedding strategy per source), §14 (M2 Learner core).
