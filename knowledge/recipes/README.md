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

Validate:

```bash
python3 server/pitch_recipes.py validate
```
