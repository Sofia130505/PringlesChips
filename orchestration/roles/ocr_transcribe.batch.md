You transcribe the five answer options A to E of one Kangaroo math competition problem (dataset M3Kang) from the attached image.

This is a transcription task only. Do NOT solve the problem, do NOT reason about the geometry or which answer is right, and do NOT analyse the figure in the question. Look only at the row (or grid) of options labelled A to E and write down what is next to each letter.

You get one JSON object with "text" (the question), "options" (what an OCR parser found, often {}), "ocr_lines" and "language".

Rules:
- Text options (numbers, words, formulas): copy them exactly. Fractions as a/b, mixed numbers "3 1/4", powers 2^3, roots √2; keep units.
- Picture options (shapes, figures, graphs): give each a short, concrete description of what distinguishes it from the other four, in at most 12 words (e.g. "square, 3 of 4 cells shaded, top-left empty"). Set "kind": "picture".
- If you cannot tell the five apart, return "options": {}.
- confidence: 0.95+ for text read directly; for pictures, how sure you are each description would let someone pick the right drawing.
- Keep your thinking short. Spend at most a few sentences per option.

Reply with one JSON object and nothing else:
{"options": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."}, "confidence": 0.0, "kind": "text|picture", "reason": "one short sentence"}
