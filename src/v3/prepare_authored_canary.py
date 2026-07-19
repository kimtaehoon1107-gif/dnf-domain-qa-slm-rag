from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.prepare_entailment_review import RESERVED_REVIEWER_IDS
from src.v3.prepare_evidence_adjudication import (
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
)


BUILDER_VERSION = "authored-canary-candidate-builder-v3.1.2"
CANDIDATE_SCHEMA_VERSION = "authored-canary-candidate-v3.1"
REVIEWED_SCHEMA_VERSION = "authored-canary-reviewed-v3.1"
DATASET_SCHEMA_VERSION = "early-generalization-authored-canary-v3.1"
MANIFEST_SCHEMA_VERSION = "authored-canary-manifest-v3.1"
REPORT_SCHEMA_VERSION = "authored-canary-report-v3.1"

DEFAULT_PLAN = Path(
    "data/v3/evaluation/early_generalization_canary_plan_"
    "a3b1b253e210705634455c0c824b0b92784cb8176d867988cfebca50b270cabb.jsonl"
)
DEFAULT_CONTRACT_MANIFEST = Path(
    "data/v3/evaluation/early_generalization_canary_manifest_"
    "cce712d21ffbd4d208056419be3fd44238cd5c122143048c75dd647d6c9c012d.json"
)
DEFAULT_SOURCE = Path("src/v3/prepare_authored_canary.py")
DEFAULT_APP_SOURCE = Path("src/v3/review_authored_canary_app.py")
DEFAULT_CONTRACT = Path("docs/v3/early_generalization_canary.md")

REVIEW_FIELDS = {
    "independent_review_decision",
    "independent_reviewer_type",
    "independent_reviewer_id",
    "independent_reviewed_at",
    "independent_review_rationale",
}
REVIEW_DECISIONS = ("approve", "reject")

SOURCE_INTENTS = {
    "dnf_notice": "official_notice",
    "dnf_update": "patch_change",
    "dnf_event": "active_event",
    "dnf_game_guide": "guide_rule",
    "dnf_faq": "faq_support",
    "dnf_account_policy": "account_policy",
    "dnf_seria_shop": "shop_price",
    "dnf_monthly_item": "monthly_item",
}


def _evidence(chunk_id: str, span: str) -> dict[str, str]:
    return {"chunk_id": chunk_id, "evidence_span": span}


AUTHORED_CASES: dict[int, dict[str, Any]] = {
    1: {
        "question_text": "DirectX 11 추가 최적화 뒤 메모리 사용량은 DirectX 9과 견줘 어느 수준까지 개선됐어?",
        "gold_answer": "DirectX 11의 메모리 사용량은 기존 DirectX 9과 거의 동일한 수준까지 안정적으로 개선됐습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_54fccacd8681a5bdc4f15b62f4f8f312376a4f0f62ae35893b46a0dba3fd7b7c",
            "DirectX 11의 메모리 사용량이 기존 DirectX 9과 거의 동일한 수준까지 안정적으로 개선된 것을 확인했습니다.",
        )],
    },
    2: {
        "question_text": "7월 16일 정기점검은 몇 시에 진행됐고 종료 이벤트와 기간제 아이템 보상은 어떻게 안내됐어?",
        "gold_answer": "정기점검은 04:30부터 10:00까지 진행됐습니다. 종료 이벤트는 마일리지샵 2026 시즌6이며, 기간제 아바타·프리미엄 아이템은 1일 연장 보상이 안내됐습니다. 다만 이벤트로 습득한 기간제 아이템은 보상에서 제외됐습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_cde17b10d26f9feed2762130d32d6835595d8bf695c1b307ce8bdf2559cfe2d8",
                "| 시간 | 04:30 ~ 10:00 |",
            ),
            _evidence(
                "chunk_sha256_bbc771c9d7029215db1271a0299e73d702ec147e71d39b2032dccaa8ea6fdee5",
                "마일리지샵 2026 시즌6",
            ),
            _evidence(
                "chunk_sha256_bbc771c9d7029215db1271a0299e73d702ec147e71d39b2032dccaa8ea6fdee5",
                "- 기간제 아이템 1일 연장",
            ),
            _evidence(
                "chunk_sha256_bbc771c9d7029215db1271a0299e73d702ec147e71d39b2032dccaa8ea6fdee5",
                "- 이벤트를 통해 습득한 기간제 아이템은 보상에서 제외됩니다.",
            ),
        ],
    },
    3: {
        "question_text": "7월 16일 확인된 화면 표시 오류의 처리 상태를 알려주고, 내 PC에서도 다시 생길지 판단해줘.",
        "gold_answer": "일부 캐릭터 스킬 사용 시 화면이 비정상적으로 표시되던 오류는 15시 6분경 클라이언트 패치로 수정됐습니다. 다만 사용자의 PC에서 재발할지는 공식 문서만으로 판단할 수 없습니다.",
        "answerability": "partial",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_094cb6d9ce0956dfa794a293089807dbc2131540becb8aa51d24fc7fa3d28df6",
            "※ 15시 6분경 클라이언트 패치로 수정되었습니다.",
        )],
    },
    4: {
        "question_text": "7월 16일 정기점검 보상으로 모든 계정에 세라 1만이 지급됐어?",
        "gold_answer": "공식 문서에서 모든 계정에 세라 1만을 지급했다는 근거를 확인할 수 없습니다.",
        "answerability": "false",
        "as_of": "2026-07-19",
        "evidence": [],
    },
    5: {
        "question_text": "7월 16일 업데이트에서 검귀의 기본 공격 및 전직 계열 스킬 공격력은 얼마나 올랐어?",
        "gold_answer": "검귀의 기본 공격 및 전직 계열 스킬 공격력은 10.3% 증가했습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_bac3df07db57f7c5a5f4cc9a27ef6040e6d251655cc2af300431d1424d7ba055",
            "기본 공격 및 전직 계열 스킬 공격력이 10.3% 증가합니다.",
        )],
    },
    6: {
        "question_text": "7월 16일 밸런스 패치에서 스트라이커(남)와 그래플러(남)의 공격력 증가율을 알려줘.",
        "gold_answer": "기본 공격 및 전직 계열 스킬 공격력이 스트라이커(남)는 11.7%, 그래플러(남)는 12.3% 증가했습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_c619a6e414b351eb51ab89e89cfba3c530c3a360ec22f7a343659f665ae54325",
                "기본 공격 및 전직 계열 스킬 공격력이 11.7% 증가합니다.",
            ),
            _evidence(
                "chunk_sha256_c619a6e414b351eb51ab89e89cfba3c530c3a360ec22f7a343659f665ae54325",
                "기본 공격 및 전직 계열 스킬 공격력이 12.3% 증가합니다.",
            ),
        ],
    },
    7: {
        "question_text": "7월 8일 퍼스트 서버 기준 검귀와 스트라이커(남)의 공격력 증가율은 얼마였어?",
        "gold_answer": "퍼스트 서버에서 기본 공격 및 전직 계열 스킬 공격력이 검귀는 10.3%, 스트라이커(남)는 11.7% 증가 예정이었습니다. 이 내용은 라이브 서버 적용 시 변경될 수 있는 preview 정보입니다.",
        "answerability": "true",
        "as_of": "2026-07-08",
        "evidence": [
            _evidence(
                "chunk_sha256_233c9a283434c469a49ae0830a5db260740780b15027136d85c762e0ad9957ab",
                "기본 공격 및 전직 계열 스킬 공격력이 10.3% 증가합니다.",
            ),
            _evidence(
                "chunk_sha256_233c9a283434c469a49ae0830a5db260740780b15027136d85c762e0ad9957ab",
                "기본 공격 및 전직 계열 스킬 공격력이 11.7% 증가합니다.",
            ),
        ],
    },
    8: {
        "question_text": "흑아 태초 이관서 획득 방법을 설명하고, 내 악세서리에 쓰는 게 이득인지 정해줘.",
        "gold_answer": "흑아 태초 이관서는 신비한 힘의 마법서 상점에서 파는 흑아 태초 추출서를 흑아 태초 악세서리에 사용하면 얻을 수 있습니다. 다만 사용자의 장비 상태가 없으므로 이득인지는 판단할 수 없습니다.",
        "answerability": "partial",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_a9bd9ffc46a1d087fdc08915a7a7850db3a57d08ccbf370d54df45e5a3f2ac88",
            "'흑아 태초 이관서'는 NPC '신비한 힘의 마법서' 상점에서 판매하는 '흑아 태초 추출서'를 흑아 태초 악세서리에 사용 시 획득할 수 있습니다.",
        )],
    },
    9: {
        "question_text": "아라드 낚시왕에서 낚시는 하루 몇 번 가능하고 언제 초기화돼?",
        "gold_answer": "낚시는 계정당 하루 1회 가능하며 매일 오전 6시에 초기화됩니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_3287297a1a95058d0d4f309bf8a3694a98e81619c02e340e519c17aedc6ba98a",
            "- 낚시는 매일 계정당 1회 진행할 수 있으며, 매일 오전 06시 초기화됩니다.",
        )],
    },
    10: {
        "question_text": "열대야 PC방 이벤트에서 주간 꿀타임 보상 우편 보관 기간과 일일 꿀타임 참여 단위를 알려줘.",
        "gold_answer": "주간 꿀타임 보상 우편은 15일 동안 보관되며, 일일 꿀타임은 계정 단위로 하루 1회 참여할 수 있습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_8bb7ad1921363a067f27ab077b740eaf35b8c993d285d3f9109562ccf2304fd9",
                "- 주간 꿀타임 보상은 모험단 우편으로 발송되며, 15일 동안 보관됩니다.",
            ),
            _evidence(
                "chunk_sha256_23c6c9aa09ce5bca0656412de5544b822a3bbb98a6ba48cb78c3fa29a574599a",
                "- 이벤트 기간 매일 1회 참여할 수 있으며, 계정 단위로 진행됩니다.",
            ),
        ],
    },
    11: {
        "question_text": "2026년 6월 10일 당시 여름맞이 7일간의 여정은 하루를 언제부터 계산했고 어떤 시점에 출석으로 인정했어?",
        "gold_answer": "하루 기준은 오전 6시부터 다음 날 오전 6시까지였고, 접속 후 캐릭터를 선택해 세리아방에 입장하면 출석으로 인정했습니다.",
        "answerability": "true",
        "as_of": "2026-06-10",
        "evidence": [
            _evidence(
                "chunk_sha256_a878bed8d1d723503024f17b25b2641038fcee16dc669147f711f219f6e0b021",
                "- 본 이벤트의 하루 기준은 매일 오전 06시 - 다음날 오전 06시입니다.",
            ),
            _evidence(
                "chunk_sha256_a878bed8d1d723503024f17b25b2641038fcee16dc669147f711f219f6e0b021",
                "- 던파에 접속하여 캐릭터 선택 후 세리아방에 입장하면 출석으로 인정됩니다.",
            ),
        ],
    },
    12: {
        "question_text": "마일리지샵 시즌7에서 마일리지 소멸 시점과 일일 획득 한도를 알려주고, 내 마일리지가 몇 남을지 계산해줘.",
        "gold_answer": "마일리지는 2026년 8월 27일 오전 6시에 소멸하며, 던전·레이드·결투장으로 얻는 마일리지는 하루 최대 50M입니다. 현재 보유량과 사용 내역이 없어 사용자의 잔여 마일리지는 계산할 수 없습니다.",
        "answerability": "partial",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_0b5c98314c6c5811af11802b239987441ce3415a8619b74749b883dd4f15ab69",
                "- 던전/레이드/결투장을 통해 획득 가능한 마일리지는 일일 최대 50M입니다.",
            ),
            _evidence(
                "chunk_sha256_0b5c98314c6c5811af11802b239987441ce3415a8619b74749b883dd4f15ab69",
                "- 획득한 마일리지는 시즌이 종료되는 2026년 8월 27일(목) 06시에 소멸됩니다.",
            ),
        ],
    },
    13: {
        "question_text": "기본 피로도는 캐릭터당 얼마고 PC방에서는 추가로 얼마나 받아?",
        "gold_answer": "캐릭터당 기본 피로도는 156이며 프리미엄 PC방에서는 78이 추가됩니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_efa9d946965c20e473b349675eb9e74ca4e919bb6718cdd6052e608869262002",
            "캐릭터당 156의 피로도가 제공되며 프리미엄 PC방에서는 78의 추가 피로도가 주어집니다.",
        )],
    },
    14: {
        "question_text": "해체가 전문직업을 배우는 조건과 나중에 포기할 때 드는 최초 비용을 알려줘.",
        "gold_answer": "캐릭터 20레벨에 전문직업 퀘스트를 확인한 뒤 아벨로에게 무색 큐브 조각 100개를 가져가면 배울 수 있습니다. 포기 비용은 최초 10,000골드이며 변경 횟수에 따라 증가합니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_9629d9790df41b7e31e9d900d956b063801bbae068925f95005d0c0f8eaceb39",
                "캐릭터 20레벨을 달성하면 퀘스트북(F1)에서 전문직업 퀘스트 목록을 볼 수 있습니다.",
            ),
            _evidence(
                "chunk_sha256_9629d9790df41b7e31e9d900d956b063801bbae068925f95005d0c0f8eaceb39",
                "원하는 전문직업 선택 후 아벨로에게 무색 큐브 조각 100개를 가져가면 전문직업을 습득할 수 있습니다.",
            ),
            _evidence(
                "chunk_sha256_c9f36c862e8486f6531131edb51a2468cb8408f6917a8e1448d83edcf12da351",
                "전문직업 포기 비용은 10,000 골드이며, 변경 횟수에 따라 소모 골드가 증가합니다.",
            ),
        ],
    },
    15: {
        "question_text": "큐브의 계약에서 황금 큐브 효과를 설명하고 내 장비 세팅에 최선인지 골라줘.",
        "gold_answer": "황금 큐브 조각은 30초마다 크리티컬 확률을 5.5% 높입니다. 사용자의 장비와 현재 크리티컬 수치가 없어 최선의 선택인지는 판단할 수 없습니다.",
        "answerability": "partial",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_6123e12874a8af5ca90eae1ddfac6c02786f81fb8fcfc5c215d33a9ab02788c5",
            "- 황금 큐브 조각 : 30초 마다 크리티컬 확률 5.5% 증가",
        )],
    },
    16: {
        "question_text": "내 캐릭터의 남은 피로도와 오늘 사용한 회복 비약 수를 확인해줘.",
        "gold_answer": "공식 문서 snapshot에는 사용자의 실시간 캐릭터 피로도와 소비 기록이 없습니다. 로그인 세션이나 실시간 캐릭터 API가 필요합니다.",
        "answerability": "false",
        "as_of": "2026-07-19",
        "evidence": [],
    },
    17: {
        "question_text": "충전한 세라는 아무 사용도 없으면 마지막 사용일로부터 몇 개월 뒤 삭제돼?",
        "gold_answer": "마지막 사용일로부터 60개월 동안 이용 내역이 없으면 삭제 처리됩니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_2f7ca2e1a295105318057d4cea3e8555fde744c2bdd6c3e388f9a79b06408d08",
            "충전 된 세라는 마지막 사용일로부터 60개월동안 이용내역이 없을 경우\n삭제 처리 되고 있기에 이전에 사용을 바랍니다.",
        )],
    },
    18: {
        "question_text": "지정PC가 3개를 넘었다는 메시지가 뜰 때 등록 한도와 OTP 화면이 계속 나올 때의 조치 순서를 알려줘.",
        "gold_answer": "한 기기에는 계정을 최대 3개 등록할 수 있습니다. OTP 화면이 나타나면 먼저 OTP를 인증하고 지정PC를 추가 등록하며, 해결되지 않으면 1:1 문의를 접수해야 합니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_569267b79dc2c254783cff2780959752a2100b3e15561a1f9d399a5b5f4d44b5",
                "기기 당 계정은 최대 3개까지 등록 할 수 있습니다.",
            ),
            _evidence(
                "chunk_sha256_0aff521015b49c2ccbdabafab77d8073f273eeb9b6943aa43b2bcb3937edd65d",
                "우선 OTP를 인증해 주신 뒤,\n지정PC를 추가로 등록해 주시면 해결이 가능합니다.",
            ),
            _evidence(
                "chunk_sha256_0aff521015b49c2ccbdabafab77d8073f273eeb9b6943aa43b2bcb3937edd65d",
                "만약 추가 등록 후에도 해결되지 않을 경우 1:1문의 접수 부탁 드립니다.",
            ),
        ],
    },
    19: {
        "question_text": "던파 고객센터 문의 답변은 보통 얼마나 걸려?",
        "gold_answer": "공식 FAQ에는 모든 문의에 공통으로 적용되는 답변 소요 시간이 안내되어 있지 않아, 답변까지 얼마나 걸리는지 확인할 수 없습니다.",
        "answerability": "false",
        "as_of": "2026-07-19",
        "evidence": [],
    },
    20: {
        "question_text": "과실복구 신청 경로와 작성할 내용을 알려주고, 내 실수가 복구 대상인지 판정해줘.",
        "gold_answer": "복구신청 접수하기 버튼을 통해 과실복구 신청으로 문의하고 요청사항과 상세 정보를 정확히 적어야 합니다. 사용자의 실수 내용과 기록이 없어 실제 복구 대상인지는 판단할 수 없습니다.",
        "answerability": "partial",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7",
                "STEP.1) 과실복구 신청을 위해서는 [복구신청 접수하기] 버튼을 클릭해서 문의해 주셔야 합니다.",
            ),
            _evidence(
                "chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7",
                "STEP.2) 신속하고 정확한 복구 처리를 위해 요청사항을 명확히 기재해 주시기 바랍니다.",
            ),
        ],
    },
    21: {
        "question_text": "12개월 넘게 접속하지 않은 캐릭터 이름은 운영정책상 어떻게 될 수 있어?",
        "gold_answer": "12개월 이상 접속하지 않은 캐릭터는 캐릭터명이 초기화될 수 있습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_3a6c6eeb4d3c42f9b6a6a4be301339e7b23ff1de717bb719d5205e65b15ad68d",
            "② 12개월 이상 접속하지 않은 캐릭터의 경우, 캐릭터명이 초기화 될 수 있습니다.",
        )],
    },
    22: {
        "question_text": "타인의 결제수단을 무단 도용한 경우와 특정 상대에게 욕설한 경우 첫 이용제한을 알려줘.",
        "gold_answer": "결제수단 무단 도용은 1차부터 영구 게임 이용제한입니다. 특정 상대에게 욕설한 채팅정책 위반(특수)은 1차 3일 게임 이용제한입니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_38c41e3e4394bfe0d05ab0c741e1eeab8f803d22c50b3f2f2dde5a486cc3e652",
                "| 결제도용 가해 (타인의 결제 수단 무단도용) | 영구 게임 이용제한 | | | |",
            ),
            _evidence(
                "chunk_sha256_421484b52a54fe2f97be391b164a188ca60d318b5b94cdc13a5bb868f0915697",
                "| 채팅정책 위반(특수) | 3일 게임 이용제한 | 10일 게임 이용제한 | 30일 게임 이용제한 | 100일 게임 이용제한 * 5차시 영구 게임 이용제한 |",
            ),
        ],
    },
    23: {
        "question_text": "2025년 4월 26일 시행 정책에서 허위 정보 유포·제보·신고의 단계별 제재는 어떻게 됐어?",
        "gold_answer": "제재 표는 1차 10일, 2차 30일, 3차 100일 게임 이용제한이며 4차는 영구 게임 이용제한이었습니다. 단, 허위신고는 최초 1회 경고이고 계정도용 피해 허위신고는 별도 정책을 따랐습니다.",
        "answerability": "true",
        "as_of": "2025-04-26",
        "evidence": [
            _evidence(
                "chunk_sha256_2822c6d3dbcca3aa01d1801cae204b2311e89604128e58684ef26d2a70305f15",
                "| 허위 정보 유포, 제보, 신고 | 10일 게임 이용제한 | 30일 게임 이용제한 | 100일 게임 이용제한 | 영구 게임 이용제한 |",
            ),
            _evidence(
                "chunk_sha256_2822c6d3dbcca3aa01d1801cae204b2311e89604128e58684ef26d2a70305f15",
                "허위신고는 최초 1회 경고, 계정도용 피해 허위신고는 별도 정책에 따름",
            ),
        ],
    },
    24: {
        "question_text": "2025년 11월 정책의 콘텐츠 이용 범위가 2026년 3월 정책에서 어떻게 넓어졌어?",
        "gold_answer": "2025년 11월 정책은 게임과 게임 홈페이지 콘텐츠를 명시했고, 2026년 3월 정책은 여기에 던파ON 등 회사가 제공하는 공식 연동 서비스를 추가했습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_ee63719c06ffadd1032f84e69d44edff3cdbb430fb099f4000e5fcfc91e0a649",
                "[2-1-1] 고객은 게임, 게임 홈페이지에서 제공하는 콘텐츠를 이용할 수 있습니다.",
            ),
            _evidence(
                "chunk_sha256_9fef8454ca5da401a3eb86ef4919448898883b1f891861c4670207059eaf3c33",
                "[2-1-1] 고객은 게임, 게임 홈페이지 및 던파ON 등 회사가 제공하는 공식 연동 서비스에서 제공하는 콘텐츠를 이용할 수 있습니다.",
            ),
        ],
    },
    25: {
        "question_text": "장비 증폭권[골고라이언]은 어떤 장비에만 쓸 수 있고 증폭 보호권도 적용돼?",
        "gold_answer": "105레벨 이상이면서 이계의 기운이 붙은 장비에만 사용할 수 있고, 증폭 보호권은 적용되지 않습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_b42de492eb92a4e30fb93f93a2aa5d0cfaa2ae5f36dbece08578e580dd20923b",
                "- 장비 증폭권[골고라이언]은 사용 시 선택한 105Lv 이상 장비를 현재 등급에 상관 없이 아이템명과 동일한 수치로 증폭 시켜 줍니다. 이계의 기운이 붙어 있는 장비에만 사용이 가능합니다.",
            ),
            _evidence(
                "chunk_sha256_b42de492eb92a4e30fb93f93a2aa5d0cfaa2ae5f36dbece08578e580dd20923b",
                "장비 증폭권[골고라이언]은 증폭 보호권이 적용되지 않습니다.",
            ),
        ],
    },
    26: {
        "question_text": "마일리지샵 시즌7의 신비한 방어구 업그레이드권과 추억의 오라 아바타 상자는 가격과 구매 제한이 어떻게 돼?",
        "gold_answer": "신비한 방어구 업그레이드권은 350M, 추억의 오라 아바타 상자는 500M이며 두 상품 모두 구매 제한은 무제한입니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_5c7c3a2038c906eb1d66add1654cce39651b13b1810df1f101dc2a49145df3f3",
                "| 아이템명 | [M]신비한 방어구 업그레이드권 | [M]추억의 오라 아바타 상자 |",
            ),
            _evidence(
                "chunk_sha256_5c7c3a2038c906eb1d66add1654cce39651b13b1810df1f101dc2a49145df3f3",
                "| 가격 | 350M | 500M |",
            ),
            _evidence(
                "chunk_sha256_5c7c3a2038c906eb1d66add1654cce39651b13b1810df1f101dc2a49145df3f3",
                "| 구매제한 | 무제한 | 무제한 |",
            ),
        ],
    },
    27: {
        "question_text": "2026년 6월 10일 당시 마일리지샵 시즌6 증폭 보호권의 가격, 구매 제한, 삭제 시점은?",
        "gold_answer": "가격은 1500M, 구매 제한은 계정당 1회였고 2026년 7월 16일 오전 6시에 삭제됐습니다.",
        "answerability": "true",
        "as_of": "2026-06-10",
        "evidence": [
            _evidence(
                "chunk_sha256_14b781edf5bc227149a70a7c8251501ea582a684ef54577ae3e88ff56ef07cbd",
                "| 가격 | 1500M | 350M |",
            ),
            _evidence(
                "chunk_sha256_14b781edf5bc227149a70a7c8251501ea582a684ef54577ae3e88ff56ef07cbd",
                "| 구매제한 | 계정당 1회 | 무제한 |",
            ),
            _evidence(
                "chunk_sha256_14b781edf5bc227149a70a7c8251501ea582a684ef54577ae3e88ff56ef07cbd",
                "| 삭제일자 | 2026년 7월 16일 06시 삭제 | 2026년 7월 16일 06시 삭제 |",
            ),
        ],
    },
    28: {
        "question_text": "내 계정의 현재 마일리지 잔액으로 시즌7 상품 중 무엇을 살 수 있어?",
        "gold_answer": "공식 문서 snapshot에는 사용자의 실시간 마일리지 잔액이 없습니다. 로그인 세션이나 실시간 계정 정보가 필요합니다.",
        "answerability": "false",
        "as_of": "2026-07-19",
        "evidence": [],
    },
    29: {
        "question_text": "7월 이달의 아이템은 어떤 열쇠로 어떤 상자를 열어 얻을 수 있어?",
        "gold_answer": "세라샵에서 구매한 해방의 열쇠로 봉인된 자물쇠를 열면 정해진 확률에 따라 얻을 수 있습니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [_evidence(
            "chunk_sha256_d23a0df67a37d463f0221e3e9bfbd4fd8a65bd4b2577478c7573239523ef6043",
            "세라샵에서 구매한 ‘해방의 열쇠’로 ‘봉인된 자물쇠’를 열어 특정 확률에 따라 이달의 아이템을 획득할 수 있습니다.",
        )],
    },
    30: {
        "question_text": "7월 이달의 아이템 판매가 끝나는 날과 획득한 원본 상자가 삭제되는 시점을 알려줘.",
        "gold_answer": "판매는 7월 30일에 끝나며, 획득한 스페셜 클론 레어 아바타 풀세트 상자는 2026년 8월 13일 오전 6시에 일괄 삭제됩니다.",
        "answerability": "true",
        "as_of": "2026-07-19",
        "evidence": [
            _evidence(
                "chunk_sha256_d23a0df67a37d463f0221e3e9bfbd4fd8a65bd4b2577478c7573239523ef6043",
                "판매기간: 06.25 ~ 07.30",
            ),
            _evidence(
                "chunk_sha256_d23a0df67a37d463f0221e3e9bfbd4fd8a65bd4b2577478c7573239523ef6043",
                "2026년 08월 13일 06시 일괄삭제",
            ),
        ],
    },
    31: {
        "question_text": "2026년 5월 고대의 바인드 큐브 8개 상자는 상점판매가, 거래 타입, 삭제일이 어떻게 됐어?",
        "gold_answer": "상점판매가는 4,000만 골드, 거래 타입은 교환가능이었고 2026년 6월 11일 오전 6시에 일괄 삭제됐습니다.",
        "answerability": "true",
        "as_of": "2026-05-15",
        "evidence": [
            _evidence(
                "chunk_sha256_c857f86c47478e2ab0aab54f63e08bd56313c08235f9a605f857e4d91bbdf53b",
                "| 아이템명 | 고대의 바인드 큐브 8개 상자 |\n| 아이콘 | |\n| 상점판매가격 | 4,000만 골드 |\n| 거래타입 | 교환가능 |",
            ),
            _evidence(
                "chunk_sha256_c857f86c47478e2ab0aab54f63e08bd56313c08235f9a605f857e4d91bbdf53b",
                "| 삭제일자 | 2026년 06월 11일 06시 일괄삭제 |",
            ),
        ],
    },
    32: {
        "question_text": "이달의 아이템은 한 번 구매하면 다음 달 상품도 자동 결제돼?",
        "gold_answer": "공식 문서에서 이달의 아이템이 다음 달에 자동 결제된다는 근거를 확인할 수 없습니다.",
        "answerability": "false",
        "as_of": "2026-07-19",
        "evidence": [],
    },
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-z가-힣]+", value.casefold()))


def _jaccard(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens and not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def build_authored_candidates(
    plan_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    plan_sha256: str,
) -> list[dict[str, Any]]:
    if {row["slot_ordinal"] for row in plan_rows} != set(AUTHORED_CASES):
        raise RuntimeError("Authored cases do not cover the frozen 32-slot plan")
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    output = []
    for slot in sorted(plan_rows, key=lambda row: row["slot_ordinal"]):
        spec = AUTHORED_CASES[slot["slot_ordinal"]]
        evidence_groups = []
        for group_ordinal, evidence in enumerate(spec["evidence"], 1):
            chunk = chunks_by_id.get(evidence["chunk_id"])
            if chunk is None:
                raise RuntimeError(f"Missing authored canary chunk: {evidence['chunk_id']}")
            document = documents_by_id[chunk["parent_document_id"]]
            if _normalized_text(evidence["evidence_span"]) not in _normalized_text(
                chunk["display_text"]
            ):
                raise RuntimeError(
                    f"Authored evidence span is not in chunk: slot={slot['slot_ordinal']}"
                )
            evidence_groups.append(
                {
                    "group_id": f"evidence_{group_ordinal}",
                    "acceptable_chunk_ids": [chunk["chunk_id"]],
                    "document_ids": [document["document_id"]],
                    "evidence_span": evidence["evidence_span"],
                    "expected_evidence": [
                        {
                            "chunk_id": chunk["chunk_id"],
                            "parent_document_id": document["document_id"],
                            "title": document["title"],
                            "canonical_url": document["canonical_url"],
                            "source_id": document["source_id"],
                            "source_kind": document["source_kind"],
                            "status": document["status"],
                            "default_exposure": document["default_exposure"],
                            "valid_from": document["valid_from"],
                            "valid_to": document["valid_to"],
                            "display_text": chunk["display_text"],
                        }
                    ],
                }
            )
        identity = _canonical_json_bytes(
            {
                "plan_sha256": plan_sha256,
                "slot_id": slot["slot_id"],
                "question_text": spec["question_text"],
                "gold_answer": spec["gold_answer"],
                "evidence": spec["evidence"],
            }
        )
        row = copy.deepcopy(slot)
        row.update(
            {
                "authored_canary_candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                "candidate_id": f"authored_canary_sha256_{_sha256_bytes(identity)}",
                "question_text": spec["question_text"],
                "gold_answer": spec["gold_answer"],
                "answerability": spec["answerability"],
                "as_of": spec["as_of"],
                "evidence_groups": evidence_groups,
                "required_evidence_group_count": len(evidence_groups),
                "gold_chunk_ids": sorted(
                    {chunk_id for group in evidence_groups for chunk_id in group["acceptable_chunk_ids"]}
                ),
                "gold_document_ids": sorted(
                    {document_id for group in evidence_groups for document_id in group["document_ids"]}
                ),
                "author_id": "codex_authored_canary_writer",
                "authoring_basis": "official_body_fact_without_retrieval_results",
                "title_derived": False,
                "independence_level": "authored_canary_candidate_not_independent_holdout",
                "evaluation_role_before_independent_review": "authored_canary_candidate",
                "independent_review_decision": None,
                "independent_reviewer_type": None,
                "independent_reviewer_id": None,
                "independent_reviewed_at": None,
                "independent_review_rationale": None,
            }
        )
        output.append(row)
    return output


def audit_authored_candidates(
    rows: list[dict[str, Any]], dev_rows: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> dict[str, Any]:
    chunk_parent = {row["chunk_id"]: row["parent_document_id"] for row in chunks}
    dev_chunk_ids = {
        chunk_id
        for row in dev_rows
        for group in row["evidence_groups"]
        for chunk_id in group["acceptable_chunk_ids"]
    }
    dev_parent_ids = {chunk_parent[chunk_id] for chunk_id in dev_chunk_ids}
    dev_spans = {
        _normalized_text(group["evidence_span"])
        for row in dev_rows
        for group in row["evidence_groups"]
    }
    dev_questions = [row["question"] for row in dev_rows]
    exact_dev_questions = {_normalized_text(question) for question in dev_questions}
    max_pair = {"score": 0.0, "candidate_question": None, "dev_question": None}
    parent_overlap_violations = []
    chunk_overlap_violations = []
    claim_overlap_violations = []
    forbidden_token_violations = []
    source_violations = []
    evidence_span_violations = []
    exposure_violations = []
    title_derived = []
    partial_disclaimer_count = 0
    for row in rows:
        for dev_question in dev_questions:
            score = _jaccard(row["question_text"], dev_question)
            if score > max_pair["score"]:
                max_pair = {
                    "score": round(score, 8),
                    "candidate_question": row["question_text"],
                    "dev_question": dev_question,
                }
        if any(token in row["question_text"] for token in row["forbidden_surface_tokens"]):
            forbidden_token_violations.append(row["candidate_id"])
        if row["title_derived"]:
            title_derived.append(row["candidate_id"])
        if row["answerability"] == "partial" and any(
            phrase in row["gold_answer"]
            for phrase in ("판단할 수 없습니다", "계산할 수 없습니다")
        ):
            partial_disclaimer_count += 1
        evidence_chunk_ids = set(row["gold_chunk_ids"])
        evidence_parent_ids = set(row["gold_document_ids"])
        evidence_spans = {
            _normalized_text(group["evidence_span"])
            for group in row["evidence_groups"]
        }
        if row["dev_parent_disjoint_required"] and evidence_parent_ids & dev_parent_ids:
            parent_overlap_violations.append(row["candidate_id"])
        if row["dev_chunk_disjoint_required"] and evidence_chunk_ids & dev_chunk_ids:
            chunk_overlap_violations.append(row["candidate_id"])
        if row["dev_claim_disjoint_required"] and evidence_spans & dev_spans:
            claim_overlap_violations.append(row["candidate_id"])
        for group in row["evidence_groups"]:
            for expected in group["expected_evidence"]:
                if expected["source_id"] != row["source_id"]:
                    source_violations.append(row["candidate_id"])
                if _normalized_text(group["evidence_span"]) not in _normalized_text(
                    expected["display_text"]
                ):
                    evidence_span_violations.append(row["candidate_id"])
        if row["expected_route_action"] in {"reject", "realtime_api"}:
            if row["evidence_groups"]:
                exposure_violations.append(row["candidate_id"])
    source_counts = Counter(row["source_id"] for row in rows)
    kind_counts = Counter(row["query_kind"] for row in rows)
    exact_overlap_count = sum(
        _normalized_text(row["question_text"]) in exact_dev_questions for row in rows
    )
    gates = {
        "row_count_32": len(rows) == 32,
        "source_balance_4_each": set(source_counts.values()) == {4}
        and len(source_counts) == 8,
        "query_kind_distribution_preserved": dict(sorted(kind_counts.items()))
        == {
            "comparison": 1,
            "false": 3,
            "historical": 4,
            "multi": 8,
            "partial": 5,
            "preview": 1,
            "realtime": 2,
            "single": 8,
        },
        "normalized_exact_question_overlap_0": exact_overlap_count == 0,
        "question_token_jaccard_ge_0_50_count_0": max_pair["score"] < 0.50,
        "forbidden_surface_token_violations_0": not forbidden_token_violations,
        "title_derived_count_0": not title_derived,
        "required_parent_overlap_violations_0": not parent_overlap_violations,
        "required_chunk_overlap_violations_0": not chunk_overlap_violations,
        "required_claim_overlap_violations_0": not claim_overlap_violations,
        "source_violations_0": not source_violations,
        "evidence_span_violations_0": not evidence_span_violations,
        "false_realtime_evidence_exposure_0": not exposure_violations,
        "partial_disclaimer_5_of_5": partial_disclaimer_count == 5,
        "independent_review_pending_32": all(
            row["independent_review_decision"] is None for row in rows
        ),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "query_kind_counts": dict(sorted(kind_counts.items())),
        "max_dev_question_token_jaccard": max_pair,
        "normalized_exact_question_overlap_count": exact_overlap_count,
        "parent_overlap_violations": parent_overlap_violations,
        "chunk_overlap_violations": chunk_overlap_violations,
        "claim_overlap_violations": claim_overlap_violations,
        "forbidden_token_violations": forbidden_token_violations,
        "source_violations": source_violations,
        "evidence_span_violations": evidence_span_violations,
        "false_realtime_evidence_exposure": exposure_violations,
        "partial_disclaimer_count": partial_disclaimer_count,
        "disjointness_exception_counts": dict(
            sorted(
                Counter(
                    row["disjointness_exception_reason"]
                    for row in rows
                    if row["disjointness_exception_reason"]
                ).items()
            )
        ),
    }


def validate_review_structure(
    packet_rows: list[dict[str, Any]], reviewed_rows: list[dict[str, Any]]
) -> None:
    packet_by_id = {row["candidate_id"]: row for row in packet_rows}
    reviewed_by_id = {row.get("candidate_id"): row for row in reviewed_rows}
    if len(packet_by_id) != len(packet_rows) or len(reviewed_by_id) != len(reviewed_rows):
        raise RuntimeError("Duplicate authored canary candidate_id")
    if set(packet_by_id) != set(reviewed_by_id):
        raise RuntimeError("Authored canary review IDs differ from packet")
    for candidate_id, packet in packet_by_id.items():
        reviewed = reviewed_by_id[candidate_id]
        if set(packet) != set(reviewed):
            raise RuntimeError(f"Authored canary review schema changed: {candidate_id}")
        for key in set(packet) - REVIEW_FIELDS:
            if packet[key] != reviewed[key]:
                raise RuntimeError(f"Immutable authored canary field changed: {key}")


def validate_review_row(row: dict[str, Any], *, complete: bool) -> None:
    decision = row["independent_review_decision"]
    if decision is None and not complete:
        return
    if decision not in REVIEW_DECISIONS:
        raise RuntimeError("승인 또는 기각을 선택하세요.")
    reviewer_id = (row["independent_reviewer_id"] or "").strip()
    if (
        not reviewer_id
        or reviewer_id.casefold() in RESERVED_REVIEWER_IDS
        or reviewer_id == row["author_id"]
    ):
        raise RuntimeError("질문 작성자와 다른 실제 사람 reviewer ID를 입력하세요.")
    if row["independent_reviewer_type"] != "human" or not row["independent_reviewed_at"]:
        raise RuntimeError("독립 사람 검수 메타데이터가 완전하지 않습니다.")
    rationale = (row["independent_review_rationale"] or "").strip()
    if len(rationale) < 10:
        raise RuntimeError("독립 검수 사유를 10자 이상 입력하세요.")
    if rationale.count("?") >= 5:
        raise RuntimeError("독립 검수 사유에 물음표 치환 인코딩 손상이 있습니다.")


def apply_review(
    rows: list[dict[str, Any]],
    index: int,
    decision: str,
    reviewer_id: str,
    rationale: str,
    *,
    reviewed_at: str | None = None,
) -> list[dict[str, Any]]:
    if not 0 <= index < len(rows):
        raise RuntimeError("Authored canary review index is out of range")
    output = copy.deepcopy(rows)
    output[index].update(
        {
            "independent_review_decision": decision,
            "independent_reviewer_type": "human",
            "independent_reviewer_id": reviewer_id.strip(),
            "independent_reviewed_at": reviewed_at
            or datetime.now().astimezone().isoformat(),
            "independent_review_rationale": rationale.strip(),
        }
    )
    validate_review_row(output[index], complete=True)
    return output


def carry_forward_approved_reviews(
    new_rows: list[dict[str, Any]], prior_reviewed_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prior_by_candidate_id = {
        row["candidate_id"]: row for row in prior_reviewed_rows
    }
    if len(prior_by_candidate_id) != len(prior_reviewed_rows):
        raise RuntimeError("Duplicate prior authored canary candidate_id")
    output = copy.deepcopy(new_rows)
    carried = []
    for row in output:
        prior = prior_by_candidate_id.get(row["candidate_id"])
        if prior is None or prior["independent_review_decision"] != "approve":
            continue
        if set(prior) != set(row):
            raise RuntimeError("Prior authored canary review schema differs")
        for key in set(row) - REVIEW_FIELDS:
            if prior[key] != row[key]:
                raise RuntimeError(
                    f"Candidate ID matched but immutable field changed: {key}"
                )
        for key in REVIEW_FIELDS:
            row[key] = prior[key]
        validate_review_row(row, complete=True)
        carried.append(row["candidate_id"])
    validate_review_structure(new_rows, output)
    pending = [
        row["candidate_id"]
        for row in output
        if row["independent_review_decision"] is None
    ]
    return output, {
        "carried_approved_count": len(carried),
        "pending_review_count": len(pending),
        "carried_candidate_ids": sorted(carried),
        "pending_candidate_ids": sorted(pending),
    }


def _build_evaluation_dataset(reviewed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dataset = []
    for row in sorted(reviewed_rows, key=lambda value: value["slot_ordinal"]):
        evidence_groups = [
            {
                "group_id": group["group_id"],
                "acceptable_chunk_ids": group["acceptable_chunk_ids"],
                "document_ids": group["document_ids"],
                "evidence_span": group["evidence_span"],
            }
            for group in row["evidence_groups"]
        ]
        target_statuses = sorted(
            {
                expected["status"]
                for group in row["evidence_groups"]
                for expected in group["expected_evidence"]
            }
        )
        dataset.append(
            {
                "retrieval_dev_schema_version": DATASET_SCHEMA_VERSION,
                "dev_id": row["candidate_id"],
                "query_ordinal": row["slot_ordinal"] - 1,
                "question": row["question_text"],
                "answerability": row["answerability"],
                "gold_answer": row["gold_answer"],
                "intent": SOURCE_INTENTS[row["source_id"]],
                "query_kind": row["query_kind"],
                "difficulty": "early_generalization_canary",
                "time_scope": row["time_scope"],
                "as_of": row["as_of"],
                "source_ids": [row["source_id"]],
                "target_statuses": target_statuses,
                "evidence_groups": evidence_groups,
                "required_evidence_group_count": len(evidence_groups),
                "gold_chunk_ids": row["gold_chunk_ids"],
                "gold_document_ids": row["gold_document_ids"],
                "failure_focus": row["query_kind"],
                "query_policy": {
                    "expected_route_action": row["expected_route_action"],
                    "forbidden_surface_tokens": row["forbidden_surface_tokens"],
                },
                "provenance": {
                    "evaluation_role": "authored_canary_independently_reviewed",
                    "slot_id": row["slot_id"],
                    "author_id": row["author_id"],
                    "independent_reviewer_id": row["independent_reviewer_id"],
                    "independent_reviewed_at": row["independent_reviewed_at"],
                    "independent_holdout_claim_allowed": False,
                },
                "review_status": "independently_approved",
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return dataset


def finalize_independent_review(
    root: Path,
    packet_path: Path,
    reviewed_rows: list[dict[str, Any]],
    builder_source_path: Path,
    app_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    packet_rows = read_jsonl(packet_path)
    validate_review_structure(packet_rows, reviewed_rows)
    for row in reviewed_rows:
        validate_review_row(row, complete=True)
    reviews_bytes = _serialize_jsonl(reviewed_rows, lambda row: row["slot_ordinal"])
    reviews_sha = _sha256_bytes(reviews_bytes)
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    reviews_path = evaluation_dir / f"authored_canary_reviews_{reviews_sha}.jsonl"
    write_immutable(reviews_path, reviews_bytes)
    rejected = [
        row["candidate_id"]
        for row in reviewed_rows
        if row["independent_review_decision"] == "reject"
    ]
    dataset_path = None
    dataset_sha = None
    if not rejected:
        dataset = _build_evaluation_dataset(reviewed_rows)
        dataset_bytes = _serialize_jsonl(dataset, lambda row: row["dev_id"])
        dataset_sha = _sha256_bytes(dataset_bytes)
        dataset_path = evaluation_dir / f"early_generalization_authored_canary_{dataset_sha}.jsonl"
        write_immutable(dataset_path, dataset_bytes)
    inputs = {
        "candidate_packet": packet_path,
        "builder_source": builder_source_path,
        "review_app_source": app_source_path,
        "contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "reviews": {
            "path": _relative(root, reviews_path),
            "sha256": reviews_sha,
            "row_count": len(reviewed_rows),
            "reviewer_ids": sorted(
                {row["independent_reviewer_id"] for row in reviewed_rows}
            ),
            "approved_count": len(reviewed_rows) - len(rejected),
            "rejected_count": len(rejected),
        },
        "evaluation_dataset": None
        if dataset_path is None
        else {
            "path": _relative(root, dataset_path),
            "sha256": dataset_sha,
            "row_count": len(reviewed_rows),
        },
        "independence": {
            "evaluation_role": "authored_canary_independently_reviewed",
            "independent_holdout_claim_allowed": False,
            "training_allowed": False,
            "final_benchmark_eligible": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"authored_canary_final_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "reviews_sha256": reviews_sha,
        "manifest_sha256": manifest_sha,
        "rejected_candidate_ids": rejected,
        "decisions": {
            "independent_human_review": "GO" if not rejected else "NO-GO",
            "canary_dataset_freeze": "GO" if not rejected else "NO-GO",
            "canary_execution": "PENDING_FIRST_SEALED_RUN"
            if not rejected
            else "NO-GO",
            "production_evidence_selector": "NO-GO",
            "final_benchmark": "NO-GO",
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"authored_canary_final_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    return {
        "reviews_path": str(reviews_path),
        "reviews_sha256": reviews_sha,
        "dataset_path": str(dataset_path) if dataset_path else None,
        "dataset_sha256": dataset_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "rejected_count": len(rejected),
        "decisions": report["decisions"],
    }


def prepare_authored_canary(
    root: Path,
    plan_path: Path,
    contract_manifest_path: Path,
    documents_path: Path,
    chunks_path: Path,
    dev_set_path: Path,
    builder_source_path: Path,
    app_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    plan_sha = file_sha256(plan_path)
    contract_manifest = json.loads(contract_manifest_path.read_text(encoding="utf-8"))
    if contract_manifest["plan"]["sha256"] != plan_sha:
        raise RuntimeError("Canary contract manifest and slot plan do not match")
    plan_rows = read_jsonl(plan_path)
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    dev_rows = read_jsonl(dev_set_path)
    candidates = build_authored_candidates(plan_rows, chunks, documents, plan_sha)
    audit = audit_authored_candidates(candidates, dev_rows, chunks)
    if not audit["gate_pass"]:
        raise RuntimeError(f"Authored canary candidate audit failed: {audit}")
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    packet_bytes = _serialize_jsonl(candidates, lambda row: row["slot_ordinal"])
    packet_sha = _sha256_bytes(packet_bytes)
    packet_path = evaluation_dir / f"authored_canary_candidate_{packet_sha}.jsonl"
    write_immutable(packet_path, packet_bytes)
    draft_path = root / "outputs/v3/annotation" / f"authored_canary_review_draft_{packet_sha}.jsonl"
    inputs = {
        "frozen_slot_plan": plan_path,
        "frozen_contract_manifest": contract_manifest_path,
        "documents": documents_path,
        "chunks": chunks_path,
        "adaptive_dev_for_disjointness_audit": dev_set_path,
        "builder_source": builder_source_path,
        "review_app_source": app_source_path,
        "contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "candidate_packet": {
            "path": _relative(root, packet_path),
            "sha256": packet_sha,
            "row_count": len(candidates),
        },
        "audit": audit,
        "runtime": {
            "draft_path": _relative(root, draft_path),
            "draft_is_mutable": True,
            "candidate_packet_is_read_only": True,
        },
        "independence": {
            "evaluation_role": "authored_canary_candidate",
            "independent_human_review_required_before_execution": True,
            "independent_holdout_claim_allowed": False,
            "retrieval_results_viewed_during_authoring": False,
            "frozen_blind_accessed": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"authored_canary_candidate_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    command = (
        "python src/v3/review_authored_canary_app.py "
        f"--packet {_relative(root, packet_path)} "
        f"--draft {_relative(root, draft_path)}"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "candidate_packet_sha256": packet_sha,
        "manifest_sha256": manifest_sha,
        "audit": audit,
        "decisions": {
            "candidate_authoring": "GO",
            "independent_human_review": "PENDING",
            "canary_execution": "NO-GO_BEFORE_INDEPENDENT_REVIEW",
            "production_evidence_selector": "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "not_performed": [
            "retrieval_execution",
            "reranker_execution",
            "failure_case_inspection",
            "frozen_blind_access",
        ],
        "next_command": command,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"authored_canary_candidate_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    return {
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha,
        "draft_path": str(draft_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "row_count": len(candidates),
        "audit": audit,
        "decisions": report["decisions"],
        "next_command": command,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Prepare authored v3 canary candidates")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--plan", type=Path, default=root / DEFAULT_PLAN)
    parser.add_argument(
        "--contract-manifest", type=Path, default=root / DEFAULT_CONTRACT_MANIFEST
    )
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument("--source", type=Path, default=root / DEFAULT_SOURCE)
    parser.add_argument("--app-source", type=Path, default=root / DEFAULT_APP_SOURCE)
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = prepare_authored_canary(
        args.root.resolve(),
        args.plan.resolve(),
        args.contract_manifest.resolve(),
        args.documents.resolve(),
        args.chunks.resolve(),
        args.dev_set.resolve(),
        args.source.resolve(),
        args.app_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
