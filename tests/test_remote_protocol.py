import json

import pytest

from screen_translator.core import OcrLine, OcrResult, TextBlock, TranslatedBlock
from screen_translator.remote import protocol


def block(block_id, *lines):
    return TextBlock(block_id, [OcrLine([(0, 0), (9, 0), (9, 9), (0, 9)], line, 0.9) for line in lines])


def test_ocr_result_survives_a_round_trip():
    original = OcrResult(
        [OcrLine([(1.5, 2.5), (9, 2.5), (9, 12), (1.5, 12)], "Hello", 0.87, "en")],
        "en",
        "CUDA",
        {"total": 42.5},
    )

    restored = protocol.decode_ocr_result(json.loads(json.dumps(protocol.encode_ocr_result(original))))

    assert restored.detected_language == "en"
    assert restored.device == "CUDA"
    assert restored.timings_ms == {"total": 42.5}
    assert [line.text for line in restored.lines] == ["Hello"]
    assert restored.lines[0].polygon == [(1.5, 2.5), (9.0, 2.5), (9.0, 12.0), (1.5, 12.0)]
    assert restored.lines[0].language == "en"


def test_translation_request_carries_text_but_no_geometry():
    payload = protocol.encode_translation_request([block("b1", "Hello", "World")], "en", "zh-Hans", None)

    assert payload["blocks"] == [{"block_id": "b1", "text": "Hello\nWorld"}]
    assert "polygon" not in json.dumps(payload)


def test_rebuilt_block_reproduces_the_original_text_exactly():
    original = block("b1", "first", "second", "third")

    rebuilt = protocol.rebuild_block(original.block_id, original.text)

    assert rebuilt.text == original.text
    assert rebuilt.block_id == original.block_id


def test_decoded_request_is_translatable_without_polygons():
    request = protocol.decode_translation_request(
        protocol.encode_translation_request([block("b1", "Hello")], "en", "zh-Hans", "en")
    )

    assert [item.text for item in request["blocks"]] == ["Hello"]
    assert request["source_language"] == "en"
    assert request["target_language"] == "zh-Hans"
    assert request["detected_language"] == "en"


def test_translation_result_reattaches_to_local_blocks_that_kept_geometry():
    local = [block("b1", "Hello")]
    values = protocol.decode_translation_result({"b1": "你好"}, ["b1"])

    translated = protocol.apply_translation(local, values)

    assert translated[0].text == "你好"
    assert translated[0].block is local[0]
    assert translated[0].block.lines[0].polygon == [(0, 0), (9, 0), (9, 9), (0, 9)]


def test_translation_result_must_match_the_requested_ids():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_translation_result({"b1": "你好", "b2": "多余"}, ["b1"])
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_translation_result({}, ["b1"])


def test_encoded_result_uses_block_ids_as_keys():
    encoded = protocol.encode_translation_result([TranslatedBlock(block("b1", "Hello"), "你好")])

    assert encoded == {"b1": "你好"}


@pytest.mark.parametrize(
    "payload",
    [
        {"blocks": []},
        {"blocks": [{"block_id": "b1"}]},
        {"blocks": [{"block_id": "b1", "text": 5}]},
        {"blocks": [{"block_id": "", "text": "x"}]},
        {"blocks": [{"block_id": "b1", "text": "x"}, {"block_id": "b1", "text": "y"}]},
        {"blocks": [{"block_id": "b1", "text": "x"}], "target_language": "fr"},
        {"blocks": [{"block_id": "b1", "text": "x"}], "source_language": "../etc"},
        {"blocks": "not-a-list"},
        "not-an-object",
    ],
)
def test_malformed_translation_requests_are_rejected(payload):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_translation_request(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"lines": [{"polygon": [[0, 0], [1, 0]], "text": "x", "confidence": 1.0}]},
        {"lines": [{"polygon": [[0, 0], [1, 0], [1, 1]], "text": "x", "confidence": "high"}]},
        {"lines": [{"polygon": [[0, 0], [1, 0], [1, 1]], "text": "x", "confidence": float("inf")}]},
        {"lines": [{"polygon": "square", "text": "x", "confidence": 1.0}]},
        {"lines": {}},
    ],
)
def test_malformed_ocr_results_are_rejected(payload):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_ocr_result(payload)


def test_oversized_payloads_are_rejected_before_allocation():
    oversized = {"blocks": [{"block_id": "b1", "text": "x" * (protocol.MAX_BLOCK_CHARACTERS + 1)}]}
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_translation_request(oversized)

    too_many = {"blocks": [{"block_id": f"b{i}", "text": "x"} for i in range(protocol.MAX_BLOCKS + 1)]}
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_translation_request(too_many)


def test_events_round_trip_and_heartbeats_are_reported_as_gaps():
    frames = [
        protocol.heartbeat().strip(),
        b"",
        protocol.encode_event(protocol.EVENT_PROGRESS, text="正在翻译 1/2").strip(),
        protocol.encode_event(protocol.EVENT_RESULT, value={"b1": "你好"}).strip(),
    ]

    events = list(protocol.iter_events(frames))

    assert events[0] is None and events[1] is None
    assert events[2] == {"type": "progress", "text": "正在翻译 1/2"}
    assert events[3] == {"type": "result", "value": {"b1": "你好"}}


def test_unknown_or_malformed_frames_are_rejected():
    with pytest.raises(protocol.ProtocolError):
        list(protocol.iter_events([b"data: {broken"]))
    with pytest.raises(protocol.ProtocolError):
        list(protocol.iter_events([b'data: {"type":"exec","cmd":"rm"}']))
    with pytest.raises(protocol.ProtocolError):
        list(protocol.iter_events([b"GET / HTTP/1.1"]))


def test_unknown_event_types_cannot_be_encoded():
    with pytest.raises(protocol.ProtocolError):
        protocol.encode_event("exec", cmd="rm")
