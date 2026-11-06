# TagBond

Escrow and dispute resolution for software releases published on GitHub, built as a GenLayer Intelligent Contract.

A client escrows a reward. A publisher posts a performance bond. When the deadline arrives the contract reads the GitHub release itself and decides in code whether the work was delivered. If the client anchored the exact sha256 of the file, a matching asset digest settles the pact with no model opinion at all. Otherwise a model is consulted only for the question code cannot answer: does the release satisfy the acceptance criteria? A staked, commit-reveal jury can overturn the automated outcome, but never without independent verification against the frozen evidence.

The central rule: **a release that is late or that an admin could have altered is not automatically a breach.** A complete release published after the deadline resolves as partially delivered. A release published in time whose asset is missing, too small or different is refunded to both sides and either party may ask the jury, because a repository admin can delete or replace assets. Only facts the publisher alone controls support NOT_DELIVERED.

## What is anchored on-chain at creation

| Anchor | Example |
| --- | --- |
| Repository | `owner/name` |
| Release tag | `v1.0.0` |
| Publisher GitHub login | `octodev` |
| Asset file name | `app-linux-x64.tar.gz` |
| Minimum asset size | `1000000` bytes |
| Expected sha256 (optional) | 64 hex characters, or empty |
| Deadline | ISO timestamp |
| Evidence host | `api.github.com` only |
| Bond and partial split | basis points |

The publisher sees every anchor before posting the bond.

## How a delivery is proven

The contract reads `https://api.github.com/repos/<repo>/releases/tags/<tag>` (and, optionally, the repository's release list) itself. A release proves delivery only if all of these hold:

1. `tag_name` equals the anchored tag
2. `author.login` equals the publisher login (case-insensitive)
3. It is not a draft and not a prerelease
4. `published_at` is inside the window between creation and deadline. This is GitHub's own server clock, which the publisher cannot choose, unlike a git commit date. A release published before the pact existed never counts.
5. The named asset exists, is `uploaded`, was uploaded by the publisher and is at least the anchored size
6. When a hash is anchored, the asset `digest` equals `sha256:<anchored hash>`

With a hash anchored, passing all six checks is proof: the exact file the client asked for is public, and the pact pays in full without consulting a model. Without a hash, the checks are necessary but not sufficient: full payment also needs an affirmative merit answer, and the silence or failure of the model never authorises payment.

## Outcomes and payouts

| Outcome | Publisher receives | Client receives |
| --- | --- | --- |
| RELEASE_DELIVERED | reward + bond | nothing |
| PARTIALLY_DELIVERED | bond + reward x partial share | rest of the reward |
| NOT_DELIVERED | nothing | reward + bond |
| UNDETERMINED | bond | reward |

| Situation | Tier 1 ruling |
| --- | --- |
| Complete release in the window, hash anchored and matching | RELEASE_DELIVERED, by code |
| Complete release in the window, no hash | RELEASE_DELIVERED, PARTIALLY_DELIVERED or UNDETERMINED by the merit answer |
| Complete release after the deadline | PARTIALLY_DELIVERED by code if hash-proven, else by the merit answer, else UNDETERMINED |
| In-time release, prerelease or asset missing, small, not uploaded by the publisher, or hash mismatch | UNDETERMINED (both refunded), jury available |
| Late release that also lacks the asset | NOT_DELIVERED if the model agrees |
| No release with the tag in a complete release list, ruled at least 24 hours after the deadline | NOT_DELIVERED if the model agrees |
| Someone else's release, a draft, a release published before the pact | ignored; UNDETERMINED |

## Rules worth knowing

- **A proven delivery cannot be appealed away.** If the hash matched, `get_jury_options` lists only RELEASE_DELIVERED, so there is nothing to appeal.
- **Early or immature rulings are rejected, not recorded.** If evidence cannot be read yet, or an empty release list is less than 24 hours after the deadline, `adjudicate` reverts and the case stays open for a later attempt.
- **Rejected payments are refunded, not stranded.** A payable call that is rejected while GEN is attached credits that GEN to the sender's withdrawable balance and returns the reason instead of reverting.
- **The jury is bounded by the evidence.** `get_jury_options` lists what a jury may decide; it can never award delivery without a release that passed every structured check, and jurors earn the same fee whichever way they vote.
- **Unjudged work is never paid without proof.** If the model gives no usable answer, `adjudicate` reverts and can be retried. After 3 days past the deadline it rules in code only: unproven deliveries become undetermined (each side refunded) and the jury can still decide.
- **One release, one reward.** When several pacts name the same repository and tag, the earliest created (by the contract's own counter) wins while the others are unsettled; the rest are refunded.

## Lifecycle

`posted` -> `active` -> `evidence_locked` -> `ruled` -> (`appeal_filed` -> `jury_voting`) -> `settled`

Every state has a way out: cancel, expire without evidence, expire unruled, settle unappealed, recover a stuck appeal. All payouts are credited to a ledger and moved only by `withdraw`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `contract.py` | Documented contract |
| `contract_deploy.py` | Generated file to paste into GenLayer Studio |
| `contract_testnet_deploy.py` | Same contract with short time windows, for live tests |
| `probe/release_probe.py` | Tiny diagnostic contract: shows what GenVM fetches from a GitHub release URL |
| `TESTNET_TESTS.md` | Live test plan and record |
| `tools/make_deploy.py` | Builds the deploy file using `ast` and `tokenize` |
| `tools/make_testnet_deploy.py` | Builds the short-window copy from the deploy file |
| `index.html` | Single-file frontend (genlayer-js from esm.sh), hash-routed, with a local sha256 file hasher |
| `tests/` | Offline tests with a self-written SDK stub |
| `ARCHITECTURE.md` | Design and disclosed limitations |

## Run the tests

No installs are needed.

```
python3 -m unittest discover -s tests
TB_CONTRACT=contract_deploy.py python3 -m unittest discover -s tests
python3 tools/make_deploy.py --check
```

## Deploy

1. Run `python3 tools/make_deploy.py` after any change to `contract.py`.
2. In GenLayer Studio, create a new contract file and paste the full content of `contract_deploy.py`. The file begins with exactly two header lines and contains no comments or docstrings, which Studio requires.
3. Deploy with no constructor arguments.
4. Open `index.html?contract=<deployed address>` once. The address is remembered in the browser.

## Methods

Writes: `create_pact`, `accept_pact`, `cancel_pact`, `submit_evidence`, `lock_evidence`, `adjudicate`, `settle_unappealed`, `expire_no_evidence`, `expire_unruled`, `recover_stuck_appeal`, `register_juror`, `unstake_juror`, `file_appeal`, `draw_jury`, `commit_vote`, `reveal_vote`, `settle_jury`, `withdraw`.

Views: `get_pact`, `list_pacts`, `get_stats`, `total_pacts`, `get_release_claim`, `get_jury_options`, `count_eligible_jurors`, `get_juror`, `get_pending_withdrawal`, `get_contract_balance`, `verify_jury_selection`.

## Status

Offline tests (350) cover the state machine, the GitHub extraction and assessment logic, hash proof, payouts, the claim registry, the jury, the deploy file and the frontend wiring, and run against both `contract.py` and `contract_deploy.py`. Three live runs on GenLayer Studio (hash-proven, unhashed model-merit and hash-proven late release, testnet variant) are recorded in `TESTNET_TESTS.md`, which also holds the plan for the paths not yet run. See `ARCHITECTURE.md` for known limitations.

## License

MIT
