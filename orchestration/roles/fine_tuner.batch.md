You write short worked solutions for Kangaroo math competition problems, used as training data for a tiny model.

You get one JSON object with "text", "options" (A-E) and "label" (the correct letter).
Write a solution of at most 3 short sentences that reaches the correct option, in the problem's language. Do not mention that you were given the answer. If the options are empty or you cannot reach the labelled answer honestly, set "answer" to null.

Reply with one JSON object and nothing else:
{"rationale": "...", "answer": "A|B|C|D|E or null"}
