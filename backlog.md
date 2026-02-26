## TODO
- more custom tools
  x - enforce git init, git cleanup, dispatch, git identity, and github token (and structure in PR description)
  x - add dispatch to custom tools
  x - actually add custom tool call to dev workflows
x - right now this kinda assumes one dev per PR. Devs should git pull at certain points (or setup_workspace should)
- move to other machine where manager can be default
- update readme
  - mention "gotchas" like picking dev comes from "main" agent right now
  - mention configs/settings for OpenClaw and git
    - requires allow tools sessions_spawn, sessions_send
    - requires local git .gitconfig for github identities
    - requires github tokens in ~/.openclaw/agents/{agent_name}/hosts.yml
x - get_pr_fix_status_checks_prompt doesnt use task files?
- test above
## Backlog
- currently dev agent is picked by "main" agent - would need inter-agent messaging to call a different agent
- it's possible multiple devs are ideal for a given issue. currently only supported by breaking up the tickets separately
- it's possible a code fix after review is better done by a different agent than the original dev. low priority. right now always picks same agent 
- move to event based instead of run every X (or just make it loop faster lol)
- PR reviewer (code-snob especially) can be wrong sometimes.
  - possible solutions
    - if reviewers disagree, the reviewers can hash it out
    - new review state where the devs/reviewers argue until decision is made
    - dev can argue the review, reviewer can re-assess, reviewers decide 
    - manager as final decision maker
    - some sort of dispute resolution criteria (majority vote override, etc)
    - human in loop
    - PR can be frozen until more information is gathered. new state needs more info
    - manager as final decision maker
