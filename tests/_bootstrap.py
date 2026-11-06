"""
Shared test bootstrap: wires up the offline genlayer SDK stub, loads the
contract once (contract.py by default, or the file named by the
TB_CONTRACT environment variable, which is how the stripped deploy file is
tested), replaces the contract's single clock with a controllable one, and
provides builders for pacts, GitHub release records and flows.
"""
import datetime as _dt
import hashlib as _hashlib
import importlib.util
import json as _json
import os
import sys
from unittest.mock import patch as _patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_DIR = os.path.join(_THIS_DIR, "genlayer_stub")
if _STUB_DIR not in sys.path:
    sys.path.insert(0, _STUB_DIR)

CONTRACT_PATH = os.environ.get("TB_CONTRACT") or os.path.join(os.path.dirname(_THIS_DIR), "contract.py")
_spec = importlib.util.spec_from_file_location("tagbond_contract", CONTRACT_PATH)
_contract_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract_module)

m = _contract_module
TagBond = m.TagBond
gl = m.gl
Address = m.Address
u256 = m.u256

# Production floors are 1e15 wei; tests use tiny amounts.
TagBond.MIN_STAKE = u256(1)
TagBond.MIN_BOND = u256(1)
TagBond.MIN_JUROR_STAKE = u256(1)
TagBond.MIN_APPEAL_BOND = u256(1)

REAL_NOW_UTC = TagBond.__dict__["_now_utc"]

UTC = _dt.timezone.utc
BASE = _dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
DAY = 86400


class Clock:
    """The contract's only clock, replaced for tests."""

    def __init__(self):
        self.now = BASE

    def reset(self):
        self.now = BASE

    def set(self, moment):
        self.now = moment

    def advance(self, seconds):
        self.now = self.now + _dt.timedelta(seconds=seconds)


CLOCK = Clock()
TagBond._now_utc = staticmethod(lambda: CLOCK.now)

PARTY_A_ADDRESS = "0x" + "11" * 20
PARTY_B_ADDRESS = "0x" + "22" * 20
STRANGER_ADDRESS = "0x" + "33" * 20
JUROR_ADDRESSES = ["0x" + hex(0xa0 + i)[2:].rjust(2, "0") * 20 for i in range(12)]

REPO = "acme/widgets"
TAG = "v1.0.0"
LOGIN = "OctoDev"
ASSET = "widgets-linux-x64.tar.gz"
MIN_BYTES = 1000
SHA = "ab" * 32
REWARD = 10000
BOND_BPS = 2000
BOND = REWARD * BOND_BPS // 10000
PARTIAL_BPS = 5000


def make_contract():
    CLOCK.reset()
    reset_transfers()
    return TagBond()


def set_caller(address_str):
    gl.message.sender_address = Address(address_str)


def reset_transfers():
    gl.evm.transfers.clear()


class PaymentRejected(gl.vm.UserError):
    """Raised by the test helper when a payable call was rejected and its
    GEN refunded to the sender (the contract does not revert in that case,
    so it can never keep GEN with no record of the sender)."""


def _state(contract):
    return (dict(contract.pacts), int(contract.pact_count), dict(contract.jurors), dict(contract.release_claims),
            int(contract.settled_count), int(contract.cancelled_count))


def call_payable(contract, method_name, value, *args, **kwargs):
    """Invoke a payable method as if `value` wei were sent with the call.

    - The value is credited to the contract balance first; if the method
      raises (only possible with no GEN attached) the credit is rolled
      back, like a reverted transaction.
    - If the method returns a rejection, the helper checks that the exact
      value was credited back to the sender and that nothing else changed,
      then raises PaymentRejected so tests can assert the rejection."""
    gl.message.value = u256(value)
    contract.balance = contract.balance + u256(value)
    sender = str(gl.message.sender_address).lower()
    before_state = _state(contract)
    before_owed = int(contract.pending_withdrawals[sender]) if sender in contract.pending_withdrawals else 0
    try:
        result = getattr(contract, method_name)(*args, **kwargs)
    except Exception:
        contract.balance = contract.balance - u256(value)
        raise
    finally:
        gl.message.value = u256(0)
    if isinstance(result, str) and result.startswith('{"refunded_wei"'):
        data = _json.loads(result)
        after_owed = int(contract.pending_withdrawals[sender]) if sender in contract.pending_withdrawals else 0
        assert data["refunded_wei"] == str(int(value)), data
        assert after_owed - before_owed == int(value), (before_owed, after_owed, value)
        assert _state(contract) == before_state, "a rejected payable call changed state"
        raise PaymentRejected(data["rejected"])
    return result


def iso(moment):
    return moment.isoformat()


def gh_ts(epoch):
    """GitHub-style timestamp for epoch seconds."""
    return _dt.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


BASE_EPOCH = int(BASE.timestamp())
DEFAULT_DEADLINE = BASE + _dt.timedelta(days=3)
DEADLINE_EPOCH = int(DEFAULT_DEADLINE.timestamp())


def release_url(tag=TAG, repo=REPO):
    return f"https://api.github.com/repos/{repo}/releases/tags/{tag}"


def list_url(repo=REPO):
    return f"https://api.github.com/repos/{repo}/releases?per_page=100"


def _apply(data, over):
    for key, value in over.items():
        if value is KeyError:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def asset_json(**over):
    """A release asset uploaded by the anchored publisher with the anchored
    name, comfortably above the minimum size. The digest is the anchored
    hash used by hash-anchored pacts."""
    data = {
        "name": ASSET,
        "size": 5000,
        "state": "uploaded",
        "uploader": {"login": LOGIN},
        "digest": "sha256:" + SHA,
        "content_type": "application/gzip",
        "download_count": 3,
        "updated_at": gh_ts(BASE_EPOCH + DAY),
    }
    return _apply(data, over)


def release_json(**over):
    """A GitHub release object: published one day after the pact was posted,
    by the anchored publisher, carrying the anchored asset."""
    data = {
        "tag_name": TAG,
        "name": "Widgets 1.0.0",
        "body": "First stable release.\n\n- sorting\n- tests",
        "draft": False,
        "prerelease": False,
        "created_at": gh_ts(BASE_EPOCH + 3600),
        "published_at": gh_ts(BASE_EPOCH + DAY),
        "author": {"login": LOGIN},
        "assets": [asset_json()],
        "html_url": "https://github.com/acme/widgets/releases/tag/v1.0.0",
    }
    return _apply(data, over)


def late_release_json(**over):
    """Complete release published only after the deadline."""
    base = dict(published_at=gh_ts(DEADLINE_EPOCH + 3600))
    base.update(over)
    return release_json(**base)


def no_asset_release_json(**over):
    """Published in time but the named asset is missing."""
    base = dict(assets=[])
    base.update(over)
    return release_json(**base)


def list_json(*releases):
    return list(releases)


def create_pact(c, reward=REWARD, deadline=None, party_a=PARTY_A_ADDRESS, party_b=PARTY_B_ADDRESS,
                repo=REPO, tag=TAG, login=LOGIN, asset=ASSET, min_bytes=MIN_BYTES, sha="",
                terms="Publish the widgets release", criteria="Release notes and the archive match the spec",
                bond_bps=BOND_BPS, partial_bps=PARTIAL_BPS):
    set_caller(party_a)
    return call_payable(
        c, "create_pact", reward, party_b, repo, tag, login, asset, min_bytes, sha, terms, criteria,
        iso(deadline or DEFAULT_DEADLINE), bond_bps, partial_bps,
    )


def accept_pact(c, pact_id, bond=BOND, party_b=PARTY_B_ADDRESS):
    set_caller(party_b)
    return call_payable(c, "accept_pact", bond, pact_id)


def get(c, pact_id):
    return _json.loads(c.get_pact(pact_id))


def submit_and_lock(c, pact_id, urls, party=PARTY_B_ADDRESS):
    """Submit evidence as `party`; if the counterparty has not answered,
    move past the grace period and lock, as a real caller would."""
    set_caller(party)
    c.submit_evidence(pact_id, urls)
    if get(c, pact_id)["status"] == "active":
        CLOCK.set(_dt.datetime.fromisoformat(get(c, pact_id)["evidence_lock_at"]) + _dt.timedelta(seconds=1))
        c.lock_evidence(pact_id)


def pass_deadline(c, pact_id):
    b = get(c, pact_id)
    deadline = _dt.datetime.fromisoformat(b["deadline"])
    if CLOCK.now <= deadline:
        CLOCK.set(deadline + _dt.timedelta(seconds=5))


def web_for(pages):
    """A render replacement: url -> text (dict and list values are
    JSON-encoded)."""
    def render(url, mode="text"):
        value = pages.get(url)
        if value is None:
            raise RuntimeError("404")
        return value if isinstance(value, str) else _json.dumps(value)
    return render


MODEL_DELIVERED = {"outcome": "RELEASE_DELIVERED", "reasoning": "criteria met"}
MODEL_PARTIAL = {"outcome": "PARTIALLY_DELIVERED", "reasoning": "substantive work"}
MODEL_UNDETERMINED = {"outcome": "UNDETERMINED", "reasoning": "thin evidence"}
MODEL_NOT_DELIVERED = {"outcome": "NOT_DELIVERED", "reasoning": "nothing published"}


def adjudicate(c, pact_id, pages, model=None, prompts=None, caller=STRANGER_ADDRESS):
    """Run adjudicate with the given fetch results and model answer.
    `model` is a dict, an Exception instance to raise, or None (the model
    must then not be called). Returns the pact dict."""
    calls = prompts if prompts is not None else []

    def exec_prompt(prompt, response_format="json"):
        calls.append(prompt)
        if model is None:
            raise AssertionError("the model must not be called here")
        if isinstance(model, Exception):
            raise model
        return model

    set_caller(caller)
    with _patch.object(gl.nondet.web, "render", side_effect=web_for(pages)), \
            _patch.object(gl.nondet, "exec_prompt", side_effect=exec_prompt):
        c.adjudicate(pact_id)
    return get(c, pact_id)


def active_pact(c, **over):
    """A pact posted and accepted at the base time."""
    pact_id = create_pact(c, **over)
    reward = over.get("reward", REWARD)
    bond_bps = over.get("bond_bps", BOND_BPS)
    accept_pact(c, pact_id, bond=reward * bond_bps // 10000)
    return pact_id


def locked_pact(c, urls=None, both=False, **over):
    """An accepted pact whose evidence is locked. With `both` the client
    answers too, so the lock happens at once and the clock does not move;
    otherwise the clock moves past the counterparty grace period."""
    urls = urls or [release_url()]
    pact_id = active_pact(c, **over)
    if both:
        set_caller(PARTY_B_ADDRESS)
        c.submit_evidence(pact_id, urls)
        set_caller(PARTY_A_ADDRESS)
        c.submit_evidence(pact_id, urls)
    else:
        submit_and_lock(c, pact_id, urls)
    return pact_id


def ruled_pact(c, pages=None, model=None, urls=None, after_deadline=True, **over):
    """A pact carried through Tier 1."""
    pages = pages if pages is not None else {release_url(): release_json()}
    pact_id = locked_pact(c, urls=urls or list(pages.keys()), **over)
    if after_deadline:
        pass_deadline(c, pact_id)
    adjudicate(c, pact_id, {u: v for u, v in pages.items()}, model=model)
    return pact_id


def register_jurors(c, count=6, base_stake=1000):
    for i, addr in enumerate(JUROR_ADDRESSES[:count]):
        set_caller(addr)
        call_payable(c, "register_juror", base_stake + i * 100)


def pass_appeal_window(c, pact_id):
    b = get(c, pact_id)
    CLOCK.set(_dt.datetime.fromisoformat(b["appeal_deadline"]) + _dt.timedelta(seconds=120))


def draw_jury(c, pact_id, beacon="fixed-test-beacon"):
    pass_appeal_window(c, pact_id)
    b = get(c, pact_id)
    page = _json.dumps({"round": b["appeal"]["draw_round"], "randomness": beacon})
    with _patch.object(gl.nondet.web, "render", return_value=page):
        c.draw_jury(pact_id)


def commit_hash(vote, salt, pact_id, juror):
    return _hashlib.sha256(f"{vote}:{salt}:{str(juror).lower()}:{pact_id}".encode()).hexdigest()


def pending(c, address):
    return int(c.get_pending_withdrawal(address))


def expect_user_error(testcase, fn, *args, **kwargs):
    with testcase.assertRaises(gl.vm.UserError) as ctx:
        fn(*args, **kwargs)
    return str(ctx.exception)


def anchors(**over):
    """The anchor fields the module-level helpers read, as a plain dict."""
    b = {
        "repo": REPO, "repo_key": REPO.lower(), "tag": TAG,
        "publisher_login": LOGIN, "publisher_key": LOGIN.lower(),
        "asset_name": ASSET, "min_asset_bytes": MIN_BYTES, "expected_sha256": "",
        "created_epoch": BASE_EPOCH, "deadline_epoch": DEADLINE_EPOCH,
        "pact_terms": "Publish the widgets release", "acceptance_criteria": "Release notes and the archive match the spec",
        "created_at": iso(BASE), "deadline": iso(DEFAULT_DEADLINE),
    }
    b.update(over)
    return b


def gather(mapping, b=None):
    """Run the contract's page gathering over a url -> content mapping."""
    with _patch.object(gl.nondet.web, "render", side_effect=web_for(mapping)):
        return m._gather_pages(list(mapping.keys()), b or anchors())


def assess(mapping, b=None):
    b = b or anchors()
    return m._assess(gather(mapping, b), b)
