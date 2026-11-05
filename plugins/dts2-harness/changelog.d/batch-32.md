### Fixed

- Intake queue: `add`, `answer`, `resolve` and the prompt hook now run their read-modify-write under the intake file lock, so concurrent hook and CLI calls no longer lose updates or hand out duplicate ids. A busy lock still never blocks a prompt.
- Intake hook: a short or unclear reply to an open clarify item (for example "yes") now answers that item instead of creating a new low-clarity item that bypassed the question budget. Long clear prompts and steers still become new items.
