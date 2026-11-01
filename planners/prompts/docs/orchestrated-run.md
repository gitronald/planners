# An orchestrated run

Used **only when the user asks for subagents or a workflow**. One `implement` of
the umbrella works through the subplans in dependency order and fans the
independent ones out. On a plan with no subplans, its independent steps take
their place: the guidance on phases, briefs, and records applies the same way,
and the steps that set a subplan's status do not.

## Order and phases

- **Scout first, then fan out.** Read the umbrella and every subplan, then group
  the subplans into phases from the execution order (`{cli} subplans {NNN}`
  prints it when the subplans declare `needs:`). Subplans with no dependency
  between them run in parallel. Read each phase's results before launching the
  next.
- **Mark the subplan active first.** Before a phase is launched, set its
  subplans to `active` and commit that change. A run whose first phase is a
  spike otherwise has nothing to commit, so the branch stays level with the
  base, the draft PR cannot open, and the plan files say nothing is in progress
  while agents are at work.
- **Re-read each subplan before starting it**, as step 4 of *Implementing one
  nested subplan* in `{cli} skill implement` describes.
- **Lay the groundwork before the fan-out.** Land what the parallel steps share
  before launching them: the scaffold, and an empty entry for each step in any
  file they would all edit. Each agent then fills in its own entry, and the
  shared file stays the orchestrator's.

## Two ways to run in parallel

Pick per phase, and say which in the brief.

| Way | Git | Fits |
|---|---|---|
| One worktree | Agents write files and never touch git. The orchestrator commits each agent's output as its own logical chunk | Short steps whose files do not overlap |
| A worktree per agent | Each agent has its own worktree, environment, and sub-branch, and commits for itself with the checks green at every commit. The orchestrator merges with `--no-ff` and resolves the conflicts | Long steps where the history of each matters, or where files overlap |

In neither way does an agent push, merge, or touch a branch that is not its own.
Two writers in one worktree share one git index, so one's commit can carry the
other's staged changes. With a worktree per agent, expect conflicts at the
merge, and have each agent mark anything temporary it added to keep its own
tree working.

## Briefing the agents

- **One shared brief.** Write the rules every agent in a fan-out follows once,
  to a file each agent reads first: where to work, what it must not touch, the
  repo's standing rules (no git, no recursive deletes, how to run the
  interpreter), and the shape of the report. Each agent's own prompt is then its
  task and its scratch directory. A brief for agents that measure says how many
  others share the machine, so timings are repeated. The report lists every
  point where what the agent found contradicts the plan.
- **Disjoint file ownership.** Every agent's brief names the paths it may touch.
  Work that would overlap is sequenced, or the orchestrator stages it outside
  the tree and places it once the owning agent has finished.
- **Name the model for every agent.** Subagents inherit the session's model
  unless told otherwise, which is rarely what a fan-out wants. Steps that turn
  on judgment (a spike, a review) get the stronger model, and mechanical ones
  the cheaper.
- **Name the directory.** A shell keeps the directory the last command left it
  in. A command that writes, and a check whose answer depends on where it runs,
  both name their directory. A shell left in a subdirectory writes generated
  files there, and a check run from a stale directory reports on the wrong tree.
- **Findings come back in the report.** An agent returns what it found as its
  final message, and keeps scripts and raw output in its scratch directory. The
  brief does not ask it to write a report file. A harness may refuse that to a
  subagent, and each agent then works around the refusal in its own way.
- **Spikes stay in scratch.** An investigative step writes nothing to the repo.
  Its findings come back through the agent's report and land in the subplan's
  Log.

## While the agents run, and after

- **The orchestrator keeps its own lane.** While agents run, work on files none
  of them owns, and read the code the plan describes. That reading is where a
  plan's own errors show up.
- **Read the evidence, not the summary.** Open what an agent produced (the
  output, the raw numbers) before using a claim. Agents report conclusions their
  own evidence does not support: a benchmark that timed a warm cache against a
  cold one, a saving counted twice. A claim that does not survive is logged as
  untested, not dropped.
- **Audit each agent's side effects.** After every hand-back, check the tree
  with `git status`, any place outside the repo the agent was allowed to write,
  and any process or port it started. Briefs are not always obeyed, and an
  agent's own account of what it touched is not a check.
- **Check the seam.** After parallel work is merged, run the checks on the
  combined tree, from more than one working directory. One step can quietly
  break what another landed, e.g. one renames a setting that the other's code
  still reads, while each branch's own tests stay green.
- **Hand work forward in writing.** What one subplan leaves for a later one is
  listed in the umbrella's Log as well as its own, so the later subplan's
  re-read finds it.

## What gets recorded

- **Truthful status.** A subplan is marked done only when its checks ran and
  passed. "Not run" and "not verified" are recorded in those words. So is who
  ran a check: a result the orchestrator re-ran is recorded differently from one
  a subagent only reported. A run that a broken script made meaningless is
  recorded as void, not deleted. A check the user waives is recorded as waived,
  and by whom.
- **Evidence names its commit.** A measurement records the commit it was taken
  at, and whether the source was fetched first. A checkout that is behind its
  remote gives a true result about stale code.
- **Scratch is not a record.** It may survive the session or it may not, so
  nothing depends on it. The Log entry for a spike carries the steps to repeat
  it, not only its result. A probe script worth running again is committed to
  the plan directory as a sidecar file. A tool the work depends on is installed
  where the next session will find it. A plan never points at a scratch path.
  When an earlier session's scratch does survive, a later one copies from it and
  builds in its own, since the old outputs are what the earlier results were
  measured on.
- **Questions are held.** Collect open questions as the run goes and ask them
  together at the end. Write them to the plan's `## Handoff` section as they
  arise, not only into the final message, so an interrupted run does not lose
  them. A step that needs a human (a decision, a manual check, access only they
  have) is marked `blocked`, and the run carries on with whatever does not
  depend on it.
- **Measure again before asking.** A question put to the user carries a number
  measured against the branch as it stands, not one copied from an earlier Log
  entry. A stale figure asks the user to decide on a problem that may no longer
  exist.
