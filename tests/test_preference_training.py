import pytest

from scripts.training.build_preference_pairs import build


def test_preference_builder_keeps_only_judged_errors():
    base = {
        "source_language": "en",
        "target_language": "zh-Hans",
        "source_text": "Open settings",
        "reference_text": "打开设置",
        "translation": "开启设置页面",
    }
    rows = [
        {**base, "id": "bad", "judge_score": 2, "judge_issue": "addition"},
        {**base, "id": "good", "judge_score": 4, "judge_issue": "none"},
    ]

    pairs = build(rows, prohibited=[])

    assert [row["id"] for row in pairs] == ["bad"]
    assert pairs[0]["chosen"] == '{"bad": "打开设置"}'
    assert pairs[0]["rejected"] == '{"bad": "开启设置页面"}'


def test_completion_logps_ignore_prompt_and_padding_labels():
    torch = pytest.importorskip("torch")
    from scripts.training.train_preference_qlora import completion_logps

    logits = torch.full((1, 4, 3), -10.0)
    logits[0, 1, 2] = 10.0
    logits[0, 2, 1] = 10.0
    labels = torch.tensor([[-100, -100, 2, 1]])

    sums, averages, counts = completion_logps(logits, labels)

    assert counts.tolist() == [2]
    assert sums.item() > -0.001
    assert averages.item() > -0.001


def test_dpo_loss_is_neutral_at_reference_and_rewards_relative_improvement():
    torch = pytest.importorskip("torch")
    from scripts.training.train_preference_qlora import dpo_loss

    reference_chosen = torch.tensor([-2.0])
    reference_rejected = torch.tensor([-0.5])
    neutral_loss, neutral_margin = dpo_loss(
        reference_chosen,
        reference_rejected,
        reference_chosen,
        reference_rejected,
        beta=0.1,
    )
    improved_loss, improved_margin = dpo_loss(
        torch.tensor([-1.0]),
        reference_rejected,
        reference_chosen,
        reference_rejected,
        beta=0.1,
    )

    assert neutral_loss.item() == pytest.approx(0.693147, abs=1e-5)
    assert neutral_margin.item() == pytest.approx(0.0)
    assert improved_margin.item() == pytest.approx(1.0)
    assert improved_loss.item() < neutral_loss.item()


def test_new_preference_adapter_uses_the_standard_qlora_shape():
    pytest.importorskip("peft")
    from scripts.training.train_preference_qlora import new_lora_config

    config = new_lora_config()

    assert config.r == 16
    assert config.lora_alpha == 32
    assert config.target_modules == "all-linear"
    assert config.use_rslora is True
