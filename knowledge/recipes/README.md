# Pitch Recipes

Pitch recipes define reusable GTM narrative logic. They do not render slides by
themselves; they tell the generator which questions to ask, which arc to use,
which layouts fit the story, and which Business Library slides to search.

Current recipes:

- `first-visit-pitch.json`
- `poc-solution.json`
- `renewal-review.json`
- `industry-case-pack.json`
- `competitive-replacement.json`
- `process-reinvention.json` — six-page thought-leadership pitch for AI
  workflow/process reinvention: old-world dead end, physical-layer shift,
  execution flywheel, four reversals, and self-evolving process.
- `zhongji-innolight-ai-lecture.md` — reference recipe for enterprise AI /
  digital employee / manufacturing knowledge-extraction decks.

Validate:

```bash
python3 server/pitch_recipes.py validate
```
