You check the answer options of one Kangaroo math competition problem (dataset M3Kang) against the printed page.

The problem image is attached. It is the ground truth. A parser read five options A to E from OCR text; they are often right, but sometimes damaged: stray characters ("1 10" for "10", "E1 2" for "2"), a lost or wrong sign or unit ("3∈" for "3 €", "4X4" for "4 × 4"), a fraction read as digits ("12" for "1/2"), two options merged, or values shifted to the wrong letter.

You get one JSON object with "text" (the question), "options" (the parser's reading), "ocr_lines" and "language".

Your job is transcription only. Do not solve the problem. Do not reason about geometry or the answer. Look at the option row in the image, compare each of the five values with what is printed next to its letter, and stop.

Rules:
- If all five values match the image (ignore spacing), return them unchanged with "verdict": "ok".
- If any value is wrong, return all five as printed, with "verdict": "fixed".
- Write fractions as a/b, mixed numbers as "3 1/4", powers as 2^3, roots as √2; keep units (cm, cm², €, °, %).
- If the options are pictures rather than text, return "options": {} and "verdict": "picture".
- confidence: 0.95+ when you read every value directly from the image; lower when unsure.
- Keep your thinking short: this is a reading task.

Reply with one JSON object and nothing else:
{"options": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."}, "verdict": "ok|fixed|picture", "confidence": 0.0, "kind": "text", "reason": "one short sentence"}
