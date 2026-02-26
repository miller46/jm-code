## TODO
- more custom tools
  - enforce git init, git cleanup, dispatch, git identity, and github token (and structure in PR description)
- move to other machine where manager can be default
- merging happens from last reviewer, merge github token should be explicitly defined
- manager should pick the agent whose decision should be cached
- right now this kinda assumes one dev per PR. Devs should git pull at certain points (or setup_workspace should)

## Backlog
- merge conflict fix sometimes picks a different dev from main dev. which might even be optimal sometimes
- move to event based instead of run every X (or just make it loop faster lol)
- PR reviewer (code-snob especially) can be wrong sometimes.
  - possible solutions
    - if reviewers disagree, the reviewers can hash it out
    - dev can make a plea, reviewer can re-assess
    - some sort of dispute resolution criteria (majority vote override, etc)
    - human in loop
    - PR can be frozen until more information is gathered
- Git names (commit info) are enforced in local .gitconfig when agents run on same machine. Standardize / enforce
- code snob a few times has done reviews on things out of scope. need local git cleanup occasionally
- sometimes see git checkout occur inside jm-code instead of in workspace. need systematic directory setting
- sometimes workspaces get messy. need systematic git cleanup