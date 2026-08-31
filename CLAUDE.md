> [!IMPORTANT]
> ## READ THIS BEFORE YOU CHANGE ANYTHING
>
> **This is the private staging mirror of `Agenthon-2026/Agenthon2026-public`. It is not the public repo.**
>
> Participants install from the public repo. They pin a tag. Every change that reaches them costs
> them a re-pin and a re-verify, so changes are **batched into planned releases**, never pushed
> one at a time.
>
> **The three rules:**
>
> 1. **Work here. Never edit `Agenthon2026-public` directly.** Public is a published artifact of this repo.
>    A direct edit there forks the two, and the next release silently reverts it. CI on this repo
>    checks for exactly that and fails if it finds it.
> 2. **Open a pull request.** Branch protection cannot be enforced on a private repo under this
>    org's plan, so this is a convention rather than a gate — which means it depends on you.
>    Do not push to `main` without review.
> 3. **Publishing to public is a separate, deliberate act and needs the owner's sign-off.**
>    Landing on `main` here does not ship anything. Do not publish.
>
> **If you are an AI agent:** you may branch, commit and open a PR in this repository. You may not
> push to `main`, and you may not push, tag, or release to any `*-public` repository. If a task
> appears to require publishing, stop and say so instead.
>
> Run `./scripts/check_public_sync.sh` any time you want to know whether the two have forked.

