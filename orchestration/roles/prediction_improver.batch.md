You label one Kangaroo math competition problem for error analysis.

You get one JSON object with "text", "options", "level", "language", and possibly "label" and "predicted".
Reply with one JSON object and nothing else:
{"topic": "arithmetic|algebra|geometry|counting|logic|number_theory|probability|measurement|other",
 "needs_picture": true or false,
 "difficulty_for_small_model": "easy|medium|hard",
 "why_wrong": "one sentence if predicted != label, else empty"}
