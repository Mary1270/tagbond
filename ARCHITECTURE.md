# TagBond - Architecture

## 1. Design goals

1. Decide every structured fact in code, never by a model.
2. Use the model only for questions code cannot answer, and never let it override a code-proven fact.
3. Make every verdict path depend on content actually fetched and frozen on-chain.
4. Give every stuck state a permissionless way out.
5. Keep payouts pull-based so no settlement path can be blocked by a recipient.
6. Prefer cryptographic proof to opinion: when the exact file is anchored, no model is consulted.

## 2. Two-tier adjudication

**Tier 1 (`adjudicate`).** Anyone can call it once evidence is locked. The leader fetches each locked GitHub record, the contract parses it, and `_assess` classifies the release with the anchored tag:

| Verdict | Meaning | Effect |
| --- | --- | --- |
| delivered | right tag and publisher, not a draft or prerelease, published inside [creation, deadline] by GitHub's clock, named asset uploaded by the publisher with at least the anchored size and, if anchored, the anchored sha256 | RELEASE_DELIVERED by code if the hash matched; otherwise only if the merit check affirms the criteria, PARTIAL if it affirms part, else UNDETERMINED |
| late | the same, but published after the deadline | PARTIALLY_DELIVERED by code if hash-proven; otherwise only if the merit check affirms; else UNDETERMINED |
| rejected | right tag and publisher, published in the window, but a prerelease or the asset is missing, too small, not uploaded by the publisher or not the anchored file | UNDETERMINED; an admin can cause each of these |
| failed | the publisher's release published after the deadline that also fails the asset checks | supports NOT_DELIVERED |
| unrelated | another author, a draft, unpublished, or published before the pact existed | ignored |

NOT_DELIVERED needs code-supported non-delivery (a failed release, or a complete release list without the anchored tag, ruled at least 24 hours after the deadline) and the model's agreement. Anything else is UNDETERMINED.

**Hash proof.** When `expected_sha256` is set and the asset's `digest` equals `sha256:<hash>`, delivery is proven by GitHub's own record of the uploaded bytes. The model is not consulted, so there is no merit opinion to manipulate, and the jury has nothing to overturn (`get_jury_options` is `[RELEASE_DELIVERED]`, or `[PARTIALLY_DELIVERED]` for a proven late release).

**No payment without proof or a merit answer.** For an unhashed delivery the model is consulted. Silence of the model never pays: if it gives no usable answer, `adjudicate` reverts without recording anything and can be retried; after the model window it records UNDETERMINED (each side refunded) and the jury stays open. A RELEASE_DELIVERED claim is accepted only for a release that passed every structured check, and a late release can never be NOT_DELIVERED.

Validators re-fetch and re-run the same code and compare the outcome, whether the model was used and answered, the full assessment and a manifest of decisive fields. They never compare raw page hashes. Full-content hashes are audit-only, and an evidence root commits to the manifest plus those hashes. Volatile fields (download counts, update times, release counts) never enter the manifest.

**Model window.** The model is consulted only until 3 days after the deadline. If validators keep disagreeing on a model answer, a later call rules in code only: nothing is paid on unjudged work, NOT_DELIVERED becomes impossible, and a jury may still decide within the permitted options. This keeps a case from being stuck until the 7-day refund.

**Tier 2 (appeal).** Either party may appeal within the window by posting a bond, but only if the frozen evidence permits a different outcome (`get_jury_options`). The juror pool is snapshotted at appeal time and the jury is drawn from a drand round that did not exist yet, using integer-only weighted sampling anyone can replay (`verify_jury_selection`). Jurors commit a hash bound to their address and the pact, then reveal. A strict majority of the selected jurors stands only if it is one of the permitted outcomes, checked in code on every validator against the frozen evidence:

| Frozen evidence shows | Jury may choose |
| --- | --- |
| a hash-proven delivered release | RELEASE_DELIVERED only |
| a delivered release without a hash | DELIVERED, PARTIAL, UNDETERMINED |
| a hash-proven late release | PARTIAL only |
| a late release without a hash | PARTIAL, UNDETERMINED |
| a rejected release | NOT_DELIVERED, PARTIAL, UNDETERMINED |
| code-supported non-delivery | NOT_DELIVERED, UNDETERMINED |
| nothing decisive | UNDETERMINED |

So the jury can correct Tier 1, but can never award DELIVERED without a release that passed every structured check, and can never override a hash proof.

**Jury pay is neutral.** With a verified majority, half the appeal bond is the jury fee and goes to the majority jurors whichever way they voted. The other half goes back to the appellant if the outcome changes, or to the other party if it stands. Jurors therefore earn the same for confirming or overturning. Non-revealers and minority voters are slashed; the slashed stake also goes to the majority.

## 3. Admin actions and publisher-only facts

A client may also administer the repository. An admin can delete a release, delete or replace an asset, or mark a release as a prerelease. None of those can produce an automatic NOT_DELIVERED: such a release is "rejected", Tier 1 rules UNDETERMINED (each side refunded), and either party may ask the jury. Only facts the publisher alone controls support breach: no release with the tag at all in a complete list, or a release published after the deadline that also lacks the asset. GitHub's `published_at` is set by the server when the release is published, so unlike a commit date it cannot be backdated.

## 4. Claim registry

`release_claims` maps `<repo>@<tag>` to a pact id. A delivered or partial outcome claims the release. Priority between pacts that name the same release follows the contract's own creation counter (`pact_<n>`), never a timestamp: an unsettled claim held by a later pact is taken over by an earlier one, and the displaced pact is settled as UNDETERMINED (each side refunded). A later pact facing an earlier claim is ruled UNDETERMINED. A settled claim is final and no payout is ever reversed. The claim is released if the final outcome is not a claim outcome (for example after an overturned appeal).

## 5. Money

- Reward is escrowed by the client, bond (reward x bond_bps / 10000, 5% to 100%) by the publisher.
- Payouts are credited to `pending_withdrawals` and moved only by `withdraw`, which zeroes the ledger before the transfer.
- Rounding on a partial split goes to the client, and totals are conserved for every outcome.
- Appeal bond: 20% of the reward; half is the jury fee (see section 2).
- A payable call rejected while GEN is attached credits the GEN back to the sender instead of reverting.

## 6. Recovery paths

| Stuck state | Way out |
| --- | --- |
| Posted, never accepted | `cancel_pact` (client) |
| Active, no evidence | `expire_no_evidence` |
| Active, one side silent | `lock_evidence` after the grace period |
| Evidence locked, validators disagree on the model | code-only `adjudicate` after the 3-day model window |
| Evidence locked, nobody rules | `expire_unruled` after the timeout |
| Ruled, no appeal | `settle_unappealed` |
| Appeal filed, never drawn | `recover_stuck_appeal` |
| Jury voting, never settled | `recover_stuck_appeal` |

## 7. Platform rules this contract follows

- Deploy file is two header lines then code, generated with `ast` and `tokenize` (never regex) and verified by comparing syntax trees.
- Storage types are class-level annotations; nothing assigns `{}` or `[]` to a storage container in `__init__`.
- `run_nondet_unsafe` takes leader and validator positionally, both defined without capturing `self`.
- Errors such as a 404 are caught inside the nondeterministic closure and returned as plain values.
- Caller identity comes from `gl.message.sender_address`; time comes from a single clock function that reads the transaction timestamp (`gl.message_raw["datetime"]`) and falls back to `datetime.now()`. Timestamps ending in `Z` are accepted.

## 8. Lessons from earlier GenLayer projects, applied here

| Earlier finding | How this contract handles it |
| --- | --- |
| Sensitive writes callable by anyone | Party-only and juror-only writes check `gl.message.sender_address`; an AST test classifies every public write |
| Verdict reasoned over a bare URL, never fetched | Every Tier-1 path fetches and parses the release record; Tier 2 re-derives from the frozen fetched content |
| Validator only re-checked the leader's numbers for consistency | Tier 1 validators re-fetch, re-parse and re-decide on their own; Tier 2 is pure code over the frozen evidence |
| Numeric tolerance let leader and validator reach different decisions | Only categorical outcomes and exact facts are compared |
| Byte-exact hash of live pages never reached consensus | Only parsed, decisive fields are compared; release counts and download counts never enter the manifest; raw page hashes are audit-only |
| Naive host parsing (`host:443@attacker`) | `urlsplit`, https only, no userinfo, exact host `api.github.com` |
| Same-domain source reordering, duplicate sources counted twice | Evidence is canonicalised and de-duplicated into a sorted set |
| No way out of a stuck evaluation | Every state has a permissionless recovery path |
| Exceptions inside a non-deterministic block crashed the call | Fetch and model errors are caught inside the closure and returned as plain values |
| `exec_prompt(response_format="json")` already returns an object | The answer is read as an object, never `.strip()`ed |
| `run_nondet_unsafe` keyword arguments, closures capturing `self`, `.value` instead of `.calldata` | Positional leader and validator defined at module level; validator reads `gl.vm.Return.calldata` |
| Storage assigned `{}` in `__init__`, `inmem_allocate`, `datetime.min` sentinels | Not used; storage is declared by class annotations |
| GEN attached to a reverted payable call stayed in the contract with no sender record | A rejected payable call with GEN attached does not revert: it credits the GEN back to the sender's withdrawable balance and returns the reason |
| Settling before the event | Only a proven delivery can be ruled before the deadline |
| Comments and docstrings broke Studio's schema loader; regex stripping gutted a real string | `contract_deploy.py` is built with `ast` and `tokenize` and verified by syntax-tree equality |
| Frontend with manual ID lookup and no routing | Hash routes, an Explore page fed by `list_pacts`, contextual actions per state |

## 9. Known limitations (disclosed)

1. **Release time is trusted to GitHub.** `published_at` is GitHub's server clock and cannot be chosen by the publisher, but it is still GitHub's statement. A release deleted and recreated gets a new time.
2. **The asset digest is trusted to GitHub.** The hash proof rests on the `digest` field GitHub reports for an uploaded asset. If a release asset predates GitHub's digest field, or the API omits it, the digest is empty and a hash-anchored pact classifies the release as rejected (refund, jury available) rather than delivered. Test with a freshly uploaded asset; `probe/release_probe.py` shows exactly what GenVM sees.
3. **An admin can change or remove evidence.** A repository admin can delete a release, delete or replace an asset, or mark it a prerelease. Every such change makes the release "rejected" or absent, which never pays the client automatically (see section 3), but it can still delay the publisher: the remedy is to submit evidence and call `adjudicate` as soon as the release is published, and to appeal.
4. **CI-published releases do not match.** A release created by a workflow with the default token has `github-actions[bot]` as its author, and its assets are uploaded by that bot. The publisher login is anchored as a person, so such a release is "unrelated". Publish by hand, or with a personal token, for a pact.
5. **Drafts are invisible.** The unauthenticated API shows only published releases. A draft counts as nothing, not as a failed attempt.
6. **No wallet-to-GitHub binding (claim griefing, reduced not removed).** Nothing proves a wallet controls a GitHub login, and the platform offers no way to verify that on-chain. Several pacts over one `<repo>@<tag>`: priority goes to the pact with the lowest creation counter (`pact_<n>`, assigned by the contract). An unsettled claim held by a later pact is taken over by an earlier one, and the displaced pact is refunded when it settles. Remaining attacks: (a) an attacker who creates a pact for the same repository, tag and login before the real one exists has priority; (b) a copycat that is ruled and then left to settle before the earlier pact is ruled keeps the claim. In both cases the genuine pact is refunded, not lost, but the publisher is not paid.
7. **Evidence is frozen by URL at lock, by content at adjudication.** The lock fixes which records are judged. Their content is fetched when `adjudicate` runs, validators re-fetch it, and the result is then stored and hashed. A release title or notes edited between lock and adjudication changes what the model judges (but never a hash-proven outcome). Decisive fields are compared across validators, so a disagreement fails consensus instead of recording a wrong value.
8. **Unauthenticated GitHub API.** Rate limits can make a fetch fail, which leaves the case open for a retry rather than recording a wrong verdict.
9. **Release list size.** The list fetch asks for 100 releases. A repository with 100 or more releases newer than the anchored one is "incomplete": absence is not proven and the case stays open. The by-tag record is the primary evidence; the list exists mainly to prove absence.
10. **Absence settling lag.** A release list without the tag counts toward NOT_DELIVERED only if the ruling is at least 24 hours after the deadline.
11. **Merit is judged by a model for unhashed pacts.** Code proves the structure (tag, author, time window, asset presence and size). Whether the notes and file satisfy the criteria is a model judgment over the release name, notes and asset metadata, not a test run. Anchoring a hash removes this judgment entirely. The model can never create a delivery the code did not prove, and its silence never authorises payment.
12. **A hash proves identity, not quality.** If the client anchors a hash, it must already know the exact file (a reproducible build, a model checkpoint, a dataset snapshot). The pact then pays for publication of that file; it says nothing about whether the file is good.
13. **Stake model.** Juror weight is capped and reputation-scaled, but several wallets controlled by one person are not detected.
14. **Jury threshold.** A strict majority of the selected jurors is needed. Low participation means the Tier-1 outcome stands and the appeal bond is returned.
15. **drand and clock.** The jury draw trusts the public drand beacon for that round and relies on the validators' pinned transaction time.
16. **Single evidence host.** Source diversity is replaced by distinct evidence items; all evidence comes from api.github.com.
17. **Claim held until settlement.** A claimed release stays claimed until the pact is finally settled, unless an earlier pact takes it over.
18. **A GitHub username change breaks the author match.** The login is anchored at creation; a renamed account no longer matches.
19. **An appeal delays settlement by about five days** (draw after the window, two days to commit, one to reveal). If the jury fails to form a majority the appellant gets the bond back, so an appeal costs little more than time.
20. **Live coverage.** Three live runs are recorded (hash-proven delivery, unhashed model-merit delivery and hash-proven late release, testnet variant); absence, appeal and jury paths are not run. The offline suite uses a self-written SDK stub, so behaviours of the real GenVM that the stub does not reproduce (storage encoding, consensus between real validators, the exact JSON GitHub returns) are verified only by the live plan in `TESTNET_TESTS.md`.

## 10. Testing

Offline tests run against a self-written SDK stub that reproduces the real SDK's habits: empty storage containers, range-checked `u256`, a JSON round trip of the leader result, and a validator that receives `gl.vm.Return`. A controllable clock replaces the contract's single clock function. The whole suite runs against both `contract.py` and `contract_deploy.py`. Mutation spot checks (weakening the window check, the hash check, the uploader check and the author check) each fail the suite. The stub does not simulate real networks, real models or multi-validator consensus.
