# goal-lit-site
Goal Lit static site (Python builder, no framework). Source of truth for the site/ folder and guard tests.
- Build: `python site/build_site.py` (output site/dist, ignored by git)
- Guards: `python tests/test_guards.py`
- Rules: see PLAN.md and tests/test_guards.py (noindex, CSP, no inline style, no ratings, ad label separation).
- Workflow: small PRs only, never push to main, merge by JunTae. Deploy is done by the Goal Lit ops bot.
