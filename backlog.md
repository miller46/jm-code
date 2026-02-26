## TODO

## Backlog
- a project could be marked for a particular dev and we can probably skip LLM call to triage. Or triage at issue-dev. To save time and reduce complexity
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
