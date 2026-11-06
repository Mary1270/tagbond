# Live test plan

Status: three paths were run on GenLayer Studio on 2026-11-06 (testnet variant): the hash-proven path, the unhashed model-merit path and the hash-proven late release. Absence, appeal and jury paths are not run yet. Fill in the "Result" column only with what you actually observed.

Use whole GEN amounts. Create the test release with a freshly uploaded asset.

## Step 0: probe

| # | Action | Expected | Result |
|---|--------|----------|--------|
| 0.1 | Deploy `probe/release_probe.py` on Studio | Deploy succeeds | |
| 0.2 | Create a GitHub release with a freshly uploaded asset | Release visible | |
| 0.3 | Call `probe` with `https://api.github.com/repos/<repo>/releases/tags/<tag>` | Call succeeds | |
| 0.4 | Call `get_last` | Shows tag, author, published_at, asset size, state, uploader and digest | Observed: all fields present, digest `sha256:` plus the file hash, uploader and author equal the publisher login |
| 0.5 | Check that digest is `sha256:` plus the file hash | Matches the hash shown on the GitHub release page | Observed: matches |

If the digest is empty, hash-anchored pacts cannot be proven; use unhashed pacts and the model path.

## Step 1: testnet contract

Deploy `contract_testnet_deploy.py` (short windows).

| # | Caller | Action | Expected | Result |
|---|--------|--------|----------|--------|
| 1.1 | client | `create_pact` with value, hash anchored | Pact `pact_0`, status posted | Observed: success (reward 2 GEN) |
| 1.2 | publisher | `accept_pact` with bond | Status active | Observed: success (bond 1 GEN) |
| 1.3 | publisher | `submit_evidence` with the by-tag URL | Stored | Observed: success |
| 1.4 | client | `submit_evidence` with the by-tag URL | Status evidence_locked | Observed: success, snapshot locked |
| 1.5 | anyone | `adjudicate` | Outcome RELEASE_DELIVERED, no model call | Observed: status ruled, RELEASE_DELIVERED, reasoning states delivery proven by code |
| 1.6 | anyone | `settle_unappealed` after the window | Status settled | Observed: success after the appeal deadline |
| 1.7 | publisher | `withdraw` | Balance received | Observed: pending withdrawal 3 GEN before, contract balance 0 after. A withdraw sent from the client wallet returned ERROR (nothing pending there), as intended |

## Step 2: other paths

| # | Caller | Action | Expected | Result |
|---|--------|--------|----------|--------|
| 2.1 | client | Pact with no release by the deadline, submit both URLs and the list URL, `adjudicate` after 24 hours | NOT_DELIVERED or open case | |
| 2.2 | client | Pact without hash, `adjudicate` after the deadline | Model merit answer | Observed (pact_1, roles swapped: client 0x72BE, publisher 0xf736): status ruled, RELEASE_DELIVERED from the model with a correct reason (asset present, 117444 bytes above the 100000 minimum); structure checks by code all true, nothing marked proven. settle_unappealed succeeded after the appeal deadline; pending withdrawal 3 GEN for the publisher, contract balance 0 after withdraw |
| 2.3 | client | `file_appeal` with bond | Appeal recorded | |
| 2.4 | juror | `register_juror`, then `commit_vote`, `reveal_vote` | Votes counted | |
| 2.5 | anyone | `settle_jury` | Jury outcome applied | |
| 2.6 | client | `cancel_pact` before acceptance | Refund in ledger | |
| 2.7 | anyone | `expire_no_evidence` after the window | Refund path | |

## Step 3: production contract

Deploy `contract_deploy.py` and repeat 1.1 to 1.7.

Note: the release for the pact must be published after `create_pact`; the first test release (`v1.0.0`) predated the pact and was not used.

## Recorded: late release (pact_2)

| Caller | Action | Observed |
|--------|--------|----------|
| client 0xf736 | `create_pact`, 2 GEN, hash anchored, deadline 13:25 UTC | success |
| publisher 0x72BE | `accept_pact`, 1 GEN | success |
| publisher | release v1.0.3 published after the deadline | GitHub published_at later than deadline_epoch |
| both | `submit_evidence` | success, snapshot locked |
| client | `adjudicate` | status ruled, PARTIALLY_DELIVERED by code, proven_late contains v1.0.3, no model call |
| client | `settle_unappealed` | success after the appeal deadline |
| both | `get_pending_withdrawal` | publisher 2 GEN (bond 1 + half of the reward 1), client 1 GEN (other half) |
| both | `withdraw` | contract balance 0 afterwards |
