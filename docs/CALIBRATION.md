# Calibration Set

The initial calibration set contains six user-supplied positive moments across two
public Twitch VODs. Only URLs, timestamps, and expected behavior are versioned.
Video, audio, transcripts, frames, models, databases, and exports remain local.

The machine-readable labels are in
`tests/calibration/twitch_known_moments.json`.

## Evaluation strategy

- Treat each supplied range as a positive region, not an exact required boundary.
- Measure whether a generated candidate overlaps the positive range and whether its
  final boundaries retain the setup and payoff.
- Add sampled negative regions outside the positives after transcripts/signals exist.
- Keep model/scoring changes only when they improve recall without flooding review
  with low-value candidates.
- Evaluate Quick, Balanced, and Deep separately because their available signals and
  expected runtime differ.

## Long-moment rule

Long moments may become an edit decision list containing several chronological spans.
For the 150-second Minecraft example, the default target is 60 seconds. Candidate
subspans should receive combined speech, excitement, audio-energy, scene/activity,
and continuity scores. The condenser retains setup/payoff context, joins nearby spans,
and cuts the lowest-value interior gaps until the duration budget is met. It must
record every source span so the export is explainable and reproducible.
