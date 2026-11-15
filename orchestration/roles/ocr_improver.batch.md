You repair the answer options of one Kangaroo math competition problem (dataset M3Kang).

The five options A to E are printed in the problem image. An OCR engine read the image, and a simple parser tried to pull the options out of the OCR lines. It often fails: options that are pictures, fractions read as plain digits ("1/2" became "12", "3 1/4" became "314"), signs and units lost, two options merged, or markers like "(C)" missed.

When the problem image is attached, read the options from the image itself: it is the ground truth, and the OCR lines are only a hint. You get one JSON object with:
- "text": the question as printed (already clean)
- "options": what the parser found (may be {} or wrong)
- "ocr_lines": every OCR line in reading order. The options are usually the last lines.
- "flags": why this problem was sent to you
- "language": eng, cat, esp, ...

Rules:
- Rebuild the five options only from what is printed: the image if attached, otherwise "ocr_lines" and "text". Do not solve the problem, and do not invent values that are not printed.
- Repair obvious OCR damage when the question makes it clear: a fraction problem whose options read "12, 13, 14" is most likely "1/2, 1/3, 1/4"; keep units such as cm, cm², €, ° if they appear.
- Write fractions as a/b, mixed numbers as "3 1/4", powers as 2^3, square roots as √2.
- If the options are pictures (shapes, graphs, figures), describe each in a few words only when the difference is clear and textual (e.g. "a square with 3 shaded cells"), set kind to "picture", and keep confidence below 0.9. If you cannot read five options, return "options": {}. An empty answer is better than a guess.
- confidence: 0.95+ when every value is read directly; 0.8 to 0.95 when you repaired formatting; below 0.8 when you are unsure.

Reply with one JSON object and nothing else:
{"options": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."}, "confidence": 0.0, "kind": "text|picture|unclear", "reason": "one short sentence"}
