"""V5 reference arithmetic, world-state replay, mask and training provenance regressions."""

import json
import random
from copy import deepcopy

import pytest

from training.faun_v5.catalog import IndexCatalog, ProjectCards
from training.faun_v5.evaluate import compare, local_endpoint
from training.faun_v5.generate import generate, parameters, state
from training.faun_v5.rules import KINDS, resolve
from training.faun_v5.tokenize import encode
from training.faun_v5.train import DEFAULTS, check_resume, finite, read_config
from training.faun_v5.validate import state_check, validate
from training.faun_v5.verify_rules import verify


@pytest.fixture
def generated(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    cards = []
    for split in ("train", "val", "test"):
        lines = []
        for i in range(3):
            uid = f"fixture:{split}:{i}"
            cards.append(
                {
                    "entity_id": uid,
                    "entity_name": "Карточка для теста",
                    "entity_category": "предмет",
                    "entity_digest": uid,
                }
            )
            lines.append(json.dumps({"source": {"entity_id": uid}}))
        (source / (split + ".jsonl")).write_text("\n".join(lines), encoding="utf-8")
    (source / "entity_index.jsonl").write_text("\n".join(map(json.dumps, cards)), encoding="utf-8")
    output = tmp_path / "dataset"
    generate(source, output, groups_per_split={s: 3 for s in ("train", "val", "test")})
    return output


def test_generator_replay_and_splits(generated):
    report = validate(generated)
    assert report["checked"] == 180
    assert report["exact_input_overlap"] == 0
    assert report["group_entity_npc_composition_overlap"] == 0
    assert report["multi_turn"] == 27


@pytest.mark.parametrize("kind", KINDS)
def test_independent_randomized_rules(kind):
    rng = random.Random(37)
    for _ in range(100):
        before = state(rng, "NPC")
        p = parameters(kind, rng, before, "жетон", "NPC")
        if kind == "catalog_lookup":
            p.update(name="Карточка", category="предмет")
        result = resolve(kind, p, before)
        assert verify(kind, p, before, result)
        assert before is not result["state_after"]
        corrupt = deepcopy(result)
        corrupt["state_after"]["coins"] += 1
        with pytest.raises(ValueError, match="Independent replay"):
            verify(kind, p, before, corrupt)


def test_equal_attack_and_disadvantage_are_arithmetic():
    before = state(random.Random(1), "NPC")
    p = dict(roll=14, modifier=3, threshold=17, damage=8)
    result = resolve("attack", p, before)
    assert result["success"]
    assert result["state_after"]["hp"] == before["hp"] - 8
    p.update(dice=[18, 7], modifier=4, threshold=12)
    result = resolve("disadvantage", p, before)
    assert result["numbers"]["total"] == 11 and not result["success"]


@pytest.mark.parametrize("raw,expected", [(1, 0), (23, 11), (24, 12)])
def test_resistance_once(raw, expected):
    before = state(random.Random(1), "NPC")
    r = resolve("damage", dict(raw=raw, immune=False, resistant=True, vulnerable=False), before)
    assert r["numbers"]["damage"] == expected


def test_death_stability_and_consciousness_differ():
    before = state(random.Random(1), "NPC")
    before.update(hp=0, conscious=False, failures=2, successes=0)
    dead = resolve("death_save", {"roll": 2}, before)
    assert dead["state_after"]["dead"]
    before.update(failures=0, successes=2)
    stable = resolve("death_save", {"roll": 12}, before)["state_after"]
    assert stable["stable"] and stable["hp"] == 0 and not stable["conscious"]
    assert stable["failures"] == stable["successes"] == 0
    recovered = resolve("death_save", {"roll": 20}, before)["state_after"]
    assert recovered["hp"] == 1 and recovered["conscious"]


@pytest.mark.parametrize("critical,expected", [(False, 1), (True, 2)])
def test_damage_at_zero(critical, expected):
    before = state(random.Random(1), "NPC")
    before.update(hp=0, conscious=False, failures=0, stable=True)
    r = resolve("damage_zero", dict(raw=2, critical=critical), before)
    assert r["state_after"]["failures"] == expected
    assert not r["state_after"]["stable"]


def test_overcast_requires_full_price_and_consent():
    before = state(random.Random(1), "NPC")
    before.update(hp=3, mp=0)
    p = dict(known=True, consent=True, mp_cost=2, payment="hp", roll=2, modifier=0, threshold=10)
    assert not resolve("overcast", p, before)["success"]
    before["hp"] = 4
    r = resolve("overcast", p, before)
    assert r["state_after"]["hp"] == 0 and not r["state_after"]["conscious"]
    assert r["numbers"]["outcome"] == "failure"
    p["consent"] = False
    assert resolve("overcast", p, before)["state_after"] == before


def test_social_high_roll_does_not_create_authority():
    before = state(random.Random(1), "NPC")
    p = dict(
        roll=20,
        modifier=8,
        threshold=12,
        authority_known=True,
        constraints_known=True,
        authority=False,
        feasible=True,
        vital_violated=False,
    )
    assert not resolve("social", p, before)["success"]
    p["authority"] = True
    assert resolve("social", p, before)["success"]
    p["constraints_known"] = False
    assert resolve("social", p, before)["numbers"]["clarification_required"]


def test_invention_rules_are_generic():
    before = state(random.Random(1), "NPC")
    before.update(materials=6, stamina=8)
    for name in ("копьё", "ремонт брони", "желоб для воды", "носилки"):
        p = dict(
            plan=name,
            needed=2,
            tools_available=True,
            supported=True,
            stamina_cost=2,
            partial_allowed=True,
            roll=10,
            modifier=2,
            threshold=14,
        )
        r = resolve("craft", p, before)
        assert r["numbers"]["outcome"] == "partial"
        assert r["state_after"]["materials"] == 4
        assert r["state_after"]["quality"] == "unfinished"
    before["capabilities"] = []
    p = {"required_capability": "flight"}
    assert not resolve("ability", p, before)["success"]
    before["capabilities"] = ["flight"]
    assert resolve("ability", p, before)["success"]


def test_trajectory_corruption_is_rejected(generated):
    lines = (generated / "train.jsonl").read_text(encoding="utf-8").splitlines()
    row = next(json.loads(x) for x in lines if json.loads(x)["trajectory"])
    state_check(row)
    row["trajectory"][0]["engine_result"]["state_after"]["coins"] += 1
    with pytest.raises(ValueError):
        state_check(row)


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict):
        assert tokenize and return_dict is False
        ids = [ord(c) for m in messages for c in m["content"]]
        return ids + ([99] if add_generation_prompt else [])


def test_mask_only_last_assistant():
    class Tokenizer(FakeTokenizer):
        def apply_chat_template(self, messages, **kw):
            assert kw["return_dict"] is False
            return [v for i, m in enumerate(messages) for v in [i + 10] * len(m["content"])]

    messages = [
        {"role": role, "content": text}
        for role, text in [
            ("system", "ss"),
            ("user", "u"),
            ("assistant", "old"),
            ("user", "next"),
            ("assistant", "new answer"),
        ]
    ]
    encoded, prefix = encode(Tokenizer(), messages)
    assert prefix == 10
    assert encoded["labels"][:10] == [-100] * 10
    assert encoded["labels"][10:] == [14] * 10
    with pytest.raises(ValueError, match="Overlength"):
        encode(Tokenizer(), messages, max_length=11)


def test_changed_profile_and_infinite_loss_are_rejected(tmp_path):
    c = {**DEFAULTS, "dataset": ".", "model_path": "base", "output": "run"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(c))
    assert read_config(path)["max_length"] == 4000
    c["max_length"] = 2048
    path.write_text(json.dumps(c))
    with pytest.raises(ValueError):
        read_config(path)
    with pytest.raises(ValueError):
        finite({"eval_loss": float("nan")})
    with pytest.raises(ValueError):
        check_resume(tmp_path / "run", tmp_path / "alien/checkpoint-1", {})


def test_sql_readonly_bound_parameter(tmp_path):
    import sqlite3

    path = tmp_path / "cards.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE cards(id TEXT,title TEXT,category TEXT,source TEXT,source_sha256 TEXT)"
        )
        conn.execute("INSERT INTO cards VALUES('one','Название','предмет','fixture','abc')")
    reader = ProjectCards(path)
    assert reader.count() == 1
    assert reader.get("one")["found"]
    assert not reader.get("one' OR 1=1 --")["found"]
    with reader.connect() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM cards")


def test_index_does_not_claim_sql(generated):
    index = IndexCatalog(generated / "entity_index.jsonl")
    result = index.get("fixture:train:0")
    assert result["unknown_properties"] and "not_direct_sql" in result["mode"]


@pytest.mark.parametrize(
    "url", ["https://example.org/v1", "http://127.0.0.1.evil/v1", "http://user:pw@localhost/v1"]
)
def test_remote_eval_blocked(url):
    with pytest.raises(ValueError):
        local_endpoint(url)


def test_comparison_rejects_different_parameters(tmp_path):
    paths = []
    for i in range(2):
        r = {
            "variant": str(i),
            "suite": "test",
            "parameters": {"max_tokens": 160 + i},
            "manifest_sha256": "abc",
            "results": [],
        }
        path = tmp_path / f"{i}.json"
        path.write_text(json.dumps(r))
        paths.append(path)
    with pytest.raises(ValueError, match="differ"):
        compare(paths)
